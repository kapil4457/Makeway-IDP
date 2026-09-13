"""ArgoCD health reporter — keeps ``DeploymentSetup`` fresh for the control plane.

Runs as a scheduled Lambda (EventBridge/CloudWatch every N minutes) and, in one
pass, mirrors each **live ArgoCD Application** on the cluster into a
``DeploymentSetup`` row via the internal API:

1. Resolve the sweep targets from the control plane: ``GET /internal/clusters``
   returns every registered cluster with its kube access (endpoint + token/CA,
   None falling back to this Lambda's ``KUBE_*`` env). Each environment gets
   its own cluster/ArgoCD, so the sweep covers all of them; an empty registry
   sweeps the single fallback cluster configured on the Lambda itself.
2. Per cluster, list ArgoCD Applications labeled ``managed-by: makeway`` (the
   env-scoped ApplicationSets under ``argocd/clusters/<env>/`` label one
   Application per ``{app}-{env}`` overlay with ``app`` / ``environment`` /
   ``managed-by``).
3. For each live Application, resolve the services of its ``(app, env)`` group
   through the control plane (``GET /internal/deployment-groups/{app}/{env}``)
   and report one ``POST /internal/deployment-setup`` per resolved service.

The control plane upserts per ``svcId``, so every pass reconciles the whole
inventory — it is naturally idempotent, and a later healthy report *clears* an
earlier error (the report DTO carries ``errorMessage`` only when the sync
failed). A failed cluster (unreachable, bad token) skips its Applications and
is counted in the sweep summary; it never blocks the other clusters.

Status mapping (drives service health on the status endpoint):

- ``healthy`` ↔ Application ``status.health.status``; ``degraded`` /
  ``unhealthy`` / ``missing`` map 1:1.
- Sync: ``status.sync.status`` — ``Synced`` (or ``Unknown`` with a non-null
  ``operationState`` *still* running) → ``success``; anything else (e.g.
  ``OutOfSync`` that never completes) → ``failed``.
- ``lastSyncedAt`` from ``operationState.finishedAt`` (or the health time);
  ArgoCD emits these as RFC3339 (e.g. ``2026-08-30T12:00:00Z``).

Cluster access mirrors Step-2 (exposed kube-apiserver + bearer token; the
reporter needs only a ``get`` on ArgoCD Applications in the ``argocd``
namespace, which the same ``makeway-worker`` ServiceAccount can carry).
"""
import base64
import json
import logging
import os
import ssl
import urllib.error
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Environment (set on the Lambda) -----------------------------------------
CONTROL_PLANE_URL = os.environ["CONTROL_PLANE_URL"].rstrip("/")
INTERNAL_API_KEY = os.environ["INTERNAL_API_KEY"]

# --- Exposed cluster access (same pattern as Step-2) -------------------------
KUBE_API_ENDPOINT = os.environ["KUBE_API_ENDPOINT"].rstrip("/")
KUBE_CA_CERT = os.environ.get("KUBE_CA_CERT", "")  # base64 CA bundle, else verify disabled
KUBE_TOKEN = os.environ["KUBE_TOKEN"]

# Namespace ArgoCD lives in.
ARGOCD_NAMESPACE = os.environ.get("ARGOCD_NAMESPACE", "argocd")


# --------------------------------------------------------------------------- #
# Low-level HTTP helpers (stdlib only — no `requests` in the Lambda)
# --------------------------------------------------------------------------- #

def _http(method: str, url: str, payload=None, headers=None, timeout: int = 60):
    data = None
    request_headers = {"User-Agent": "makeway-health-reporter"}
    if headers:
        request_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(
        url, data=data, headers=request_headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            body = json.loads(raw) if raw else None
            return response.status, body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        return exc.code, body


def _control_plane(method: str, path: str, payload=None):
    status, body = _http(
        method,
        f"{CONTROL_PLANE_URL}{path}",
        payload,
        {"X-Internal-API-Key": INTERNAL_API_KEY},
    )
    if not 200 <= status < 300:
        detail = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)
        raise RuntimeError(f"control-plane {method} {path} -> HTTP {status}: {detail}")
    return body


# --------------------------------------------------------------------------- #
# Kubernetes API access (stdlib HTTPS + bearer token)
# --------------------------------------------------------------------------- #

_kube_ssl_contexts: dict[str, ssl.SSLContext] = {}


def _kube_ssl_context(ca_cert: str | None = None) -> ssl.SSLContext:
    """SSL context for a kube-apiserver call, cached per CA bundle.

    Accepts an optional per-cluster CA (from the cluster registry row);
    when absent it falls back to the module global KUBE_CA_CERT. A populated
    CA enables real verification. An empty CA (the pinggy raw-TCP reality —
    the cluster's self-signed cert SANs never match the tunnel host) disables
    verification with a loud warning; the bearer token is still the auth
    boundary. One no-verify context is shared under the empty-CA key.
    """
    ca = ca_cert if ca_cert is not None else KUBE_CA_CERT
    cached = _kube_ssl_contexts.get(ca)
    if cached is not None:
        return cached

    if ca:
        context = ssl.create_default_context(cafile=None)
        context.load_verify_locations(
            cadata=base64.b64decode(ca).decode("utf-8")
        )
    else:
        logger.warning(
            "no CA cert for this cluster API — TLS verification DISABLED. "
            "Set KUBE_CA_CERT or the cluster's kubeCaCert in production."
        )
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    _kube_ssl_contexts[ca] = context
    return context


def _kube(
    method: str,
    path: str,
    payload=None,
    *,
    endpoint: str | None = None,
    token: str | None = None,
    ca_cert: str | None = None,
):
    """Raw call to a (exposed) kube-apiserver. Returns (status, body).

    ``endpoint``/``token``/``ca_cert`` override the module globals —
    per-cluster selection sourced from the control-plane registry. None
    falls back to KUBE_API_ENDPOINT / KUBE_TOKEN / KUBE_CA_CERT.
    """
    url = f"{(endpoint or KUBE_API_ENDPOINT).rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {token or KUBE_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(url, headers=headers, method=method)
    if payload is not None:
        request.data = json.dumps(payload).encode("utf-8")
    try:
        with urllib.request.urlopen(
            request, context=_kube_ssl_context(ca_cert=ca_cert), timeout=90
        ) as response:
            raw = response.read().decode("utf-8")
            body = json.loads(raw) if raw else None
            return response.status, body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        return exc.code, body


# --------------------------------------------------------------------------- #
# ArgoCD Application → (app, env) resolution
# --------------------------------------------------------------------------- #

def _list_managed_applications(
    *, endpoint: str | None = None, token: str | None = None, ca_cert: str | None = None
) -> list[dict]:
    """All ArgoCD Applications owned by Makeway (label ``managed-by: makeway``)
    on the given cluster; None creds fall back to the Lambda env."""
    status, body = _kube(
        "GET",
        (
            f"/apis/argoproj.io/v1alpha1/namespaces/{ARGOCD_NAMESPACE}/applications"
            "?labelSelector=managed-by%3Dmakeway"
        ),
        endpoint=endpoint,
        token=token,
        ca_cert=ca_cert,
    )
    if not 200 <= status < 300:
        raise RuntimeError(f"kube list Applications -> HTTP {status}")
    return (body or {}).get("items") or []


def _app_labels(app: dict) -> tuple[str | None, str | None]:
    metadata = (app or {}).get("metadata") or {}
    labels = metadata.get("labels") or {}
    return labels.get("app"), labels.get("environment")


# --------------------------------------------------------------------------- #
# Sweep targets: one cluster (its kube access) per environment
# --------------------------------------------------------------------------- #

def _fetch_clusters() -> list[dict]:
    """Registered clusters + their kube access, from the control-plane registry.

    Each environment maps to its own cluster (its own ArgoCD), so this is the
    per-env source of truth for where to sweep. Never raises for an empty
    registry — the caller falls back to this Lambda's own ``KUBE_*`` env.
    """
    body = _control_plane("GET", "/internal/clusters")
    return (body or {}).get("clusters") or []


def _sweep_targets(clusters: list[dict]) -> list[dict]:
    """Sweep list of ``{clusterName, environment, endpoint, token, caCert}``.

    One entry per registered cluster; per-field None falls back to the
    Lambda env ``KUBE_*`` inside ``_kube`` (the same semantics as Step-2's
    per-claim resolution). An empty registry sweeps the single fallback
    cluster configured on the Lambda itself.
    """
    if not clusters:
        return [
            {
                "clusterName": "fallback",
                "environment": None,
                "endpoint": None,
                "token": None,
                "caCert": None,
            }
        ]
    return [
        {
            "clusterName": c.get("clusterName") or f"cluster-{c.get('clusterId')}",
            "environment": c.get("environment"),
            "endpoint": c.get("kubeApiEndpoint"),
            "token": c.get("kubeToken"),
            "caCert": c.get("kubeCaCert"),
        }
        for c in clusters
    ]


# --------------------------------------------------------------------------- #
# Status mapping
# --------------------------------------------------------------------------- #

def _report_for(app: dict) -> dict:
    """Map an ArgoCD Application's status onto the deployment-setup report.

    The control plane's read side treats ``success`` as healthy, ``failed``
    (or a non-empty ``errorMessage``) as unhealthy, and everything else as
    unknown — so the mappings below deliberately stay on those verbs:

    - ``Healthy``                                   -> ``success``
    - ``Degraded`` / ``Missing``                    -> ``failed``
    - failed ``operationState.phase``               -> ``failed``
    - ``Suspended``                                 -> ``suspended``
    - mid-sync (``operationState.phase=Running``)   -> ``progressing``
    - ``Synced`` but health not computed yet        -> ``synced``
    - anything else (never synced, Unknown, empty)  -> ``unknown``

    ``errorMessage`` is set only for the failed cases, and always cleared
    otherwise — combined with the control plane's upsert, a later healthy
    report erases an earlier error.
    """
    app_name = (app.get("metadata") or {}).get("name", "unknown-app")
    app_status = app.get("status") or {}
    health = (app_status.get("health") or {}).get("status")
    sync = (app_status.get("sync") or {}).get("status") or "Unknown"
    op = app_status.get("operationState") or {}
    phase = op.get("phase")
    error = op.get("message") if phase == "Failed" else None

    if health == "Healthy":
        status = "success"
    elif health in ("Degraded", "Missing"):
        status = "failed"
    elif health == "Suspended":
        status = "suspended"
    elif phase == "Failed":
        status = "failed"
    elif phase == "Running":
        status = "progressing"
    elif sync == "Synced":
        status = "synced"
    else:
        status = "unknown"

    return {
        "status": status,
        "argocdAppName": app_name,
        "lastSyncedAt": op.get("finishedAt") or None,
        "errorMessage": error if status == "failed" else None,
    }


def _report_batch(app: dict, svc_ids: list[int]) -> list[dict]:
    """One deployment-setup report per service in the group, sharing the
    Application's health/sync/error state."""
    base = _report_for(app)
    batch = []
    for svc_id in svc_ids:
        payload = {
            "svcId": svc_id,
            "status": base["status"],
            "argocdAppName": base["argocdAppName"],
            "lastSyncedAt": base["lastSyncedAt"],
        }
        if base["status"] == "failed":
            payload["errorMessage"] = (
                base["errorMessage"]
                or f"ArgoCD Application {base['argocdAppName']} is not healthy"
            )
        batch.append(payload)
    return batch


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def handler(event, context):
    """Scheduled sweep: report every live Makeway Application on every
    registered cluster to the control plane."""
    clusters = _fetch_clusters()
    targets = _sweep_targets(clusters)
    logger.info(
        "sweeping %d cluster(s): %s",
        len(targets),
        ", ".join(target["clusterName"] for target in targets),
    )

    applications = 0
    reported = 0
    skipped = 0
    failed = 0
    for target in targets:
        cluster_name = target["clusterName"]
        try:
            apps = _list_managed_applications(
                endpoint=target["endpoint"],
                token=target["token"],
                ca_cert=target["caCert"],
            )
        except Exception as exc:  # noqa: BLE001 — one dead cluster must not kill the sweep
            logger.exception("list Applications failed on cluster %s: %s", cluster_name, exc)
            failed += 1
            continue

        logger.info(
            "cluster %s: found %d managed ArgoCD Applications", cluster_name, len(apps)
        )
        applications += len(apps)

        for app in apps:
            app_name, env = _app_labels(app)
            if not (app_name and env):
                logger.warning(
                    "Application %s missing app/environment labels — skipping",
                    (app.get("metadata") or {}).get("name"),
                )
                skipped += 1
                continue

            app_meta_name = (app.get("metadata") or {}).get("name", "unknown")
            try:
                group = _control_plane(
                    "GET", f"/internal/deployment-groups/{app_name}/{env}"
                )
                svc_ids = group.get("svcIds") or []
                if not svc_ids:
                    # No services in this app-env group yet (app deleted services or
                    # a stale ArgoCD Application) — nothing to report.
                    skipped += 1
                    continue

                batch = _report_batch(app, svc_ids)
                for payload in batch:
                    _control_plane("POST", "/internal/deployment-setup", payload)
                reported += len(batch)
            except Exception as exc:  # noqa: BLE001 — one bad app must not kill the sweep
                logger.exception(
                    "report failed for Application %s (%s): %s",
                    app_meta_name,
                    f"{app_name}-{env}",
                    exc,
                )
                failed += 1

    logger.info(
        "health sweep complete: %d reported, %d skipped, %d failed",
        reported,
        skipped,
        failed,
    )
    return {
        "clusters": len(targets),
        "applications": applications,
        "reported": reported,
        "skipped": skipped,
        "failed": failed,
    }