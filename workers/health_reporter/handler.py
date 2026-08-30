"""ArgoCD health reporter — keeps ``DeploymentSetup`` fresh for the control plane.

Runs as a scheduled Lambda (EventBridge/CloudWatch every N minutes) and, in one
pass, mirrors each **live ArgoCD Application** on the cluster into a
``DeploymentSetup`` row via the internal API:

1. List ArgoCD Applications labeled ``managed-by: makeway`` (the ApplicationSet
   in ``argocd/root-application.yaml`` labels one Application per ``{app}-{env}``
   overlay with ``app`` / ``environment``/``managed-by``).
2. For each live Application, resolve the services of its ``(app, env)`` group
   through the control plane (``GET /internal/deployment-groups/{app}/{env}``)
   and report one ``POST /internal/deployment-setup`` per resolved service.

The control plane upserts per ``svcId``, so every pass reconciles the whole
inventory — it is naturally idempotent, and a later healthy report *clears* an
earlier error (the report DTO carries ``errorMessage`` only when the sync
failed).

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

_ssl_context: ssl.SSLContext | None = None


def _kube_ssl_context() -> ssl.SSLContext:
    """SSL context for the kube-apiserver call (mirrors Step-2)."""
    global _ssl_context
    if _ssl_context is None:
        if KUBE_CA_CERT:
            context = ssl.create_default_context(cafile=None)
            context.load_verify_locations(
                cadata=base64.b64decode(KUBE_CA_CERT).decode("utf-8")
            )
            _ssl_context = context
        else:
            logger.warning(
                "KUBE_CA_CERT is unset — TLS verification against the exposed "
                "cluster is DISABLED. Set the CA bundle in production."
            )
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            _ssl_context = context
    return _ssl_context


def _kube(method: str, path: str, payload=None):
    url = f"{KUBE_API_ENDPOINT}{path}"
    headers = {
        "Authorization": f"Bearer {KUBE_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(url, headers=headers, method=method)
    if payload is not None:
        request.data = json.dumps(payload).encode("utf-8")
    try:
        with urllib.request.urlopen(
            request, context=_kube_ssl_context(), timeout=90
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

def _list_managed_applications() -> list[dict]:
    """All ArgoCD Applications owned by Makeway (label ``managed-by: makeway``)."""
    status, body = _kube(
        "GET",
        (
            f"/apis/argoproj.io/v1alpha1/namespaces/{ARGOCD_NAMESPACE}/applications"
            "?labelSelector=managed-by%3Dmakeway"
        ),
    )
    if not 200 <= status < 300:
        raise RuntimeError(f"kube list Applications -> HTTP {status}")
    return (body or {}).get("items") or []


def _app_labels(app: dict) -> tuple[str | None, str | None]:
    metadata = (app or {}).get("metadata") or {}
    labels = metadata.get("labels") or {}
    return labels.get("app"), labels.get("environment")


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
    """Scheduled sweep: report every live Makeway Application to the control plane."""
    apps = _list_managed_applications()
    logger.info("found %d managed ArgoCD Applications", len(apps))

    reported = 0
    skipped = 0
    failed = 0
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
        "applications": len(apps),
        "reported": reported,
        "skipped": skipped,
        "failed": failed,
    }