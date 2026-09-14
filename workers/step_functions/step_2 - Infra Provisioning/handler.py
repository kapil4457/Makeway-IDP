"""Step 2 — Crossplane Infra Provisioning worker for the Makeway app-creation
state machine.

Consumed as a Lambda task by the app-creation state machine (the same function
is invoked three times with a different ``action``):

apply
    Marks the job IN_PROGRESS, pulls the request details from the control plane,
    and for every capability renders one or more Crossplane XR instances
    (namespaced composite resources) and applies them into the ``{appName}-{env}``
    namespace. For RDS it also generates the master password and writes the
    ``{claimName}-creds`` Secret the Composition references.
check
    Queries each XR instance's ``status.conditions`` for Ready+Synced. Returns
    ``{ready, pending, attempt}``; the state machine loops (Wait -> check ->
    Choice) until ready or the attempt budget is exhausted.
extract
    Reads each XR instance's connection Secret (``{claimName}-connection-details``
    in the XR's namespace, written by the function-patch-and-transform function),
    mirrors the credentials into
    AWS Secrets Manager, and — for capabilities that grant AWS API access
    (S3/SQS/SNS) — provisions a scoped IAM user + access keys so pods on the
    local cluster (no IRSA) can call the AWS API. It then commits an
    ExternalSecret per capability into the gitops env overlay so ESO
    materializes the K8s Secret. Finally it reports per-capability results
    (outputRef / secretRef / status) back to the control plane.

Idempotency: XR instance names are deterministic (``{app}-{env}-{slug}``) and applied
with an upsert (POST on 404, PATCH otherwise), IAM users/policies/keys are
create-or-reuse, and Secrets Manager puts are idempotent. If the job already
reached ``success`` the handler exits early.

Cluster access: the Lambda reaches the (exposed) cluster API over HTTPS with a
bearer token (KUBE_API_ENDPOINT / KUBE_CA_CERT / KUBE_TOKEN env vars). The
Crossplane ProviderConfig on the cluster and this Lambda must target the same
AWS account — the extract phase builds resource ARNs from that account.
"""

import base64
import json
import logging
import os
import re
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Environment (set on the Lambda) -----------------------------------------
CONTROL_PLANE_URL = os.environ["CONTROL_PLANE_URL"].rstrip("/")
INTERNAL_API_KEY = os.environ["INTERNAL_API_KEY"]
REGION = os.environ.get("AWS_REGION", "ap-south-1")
DEFAULT_REGION = os.environ.get("DEFAULT_REGION", REGION)

# --- Exposed cluster access --------------------------------------------------
# The cluster runs on the developer's machine with ArgoCD + Crossplane; the
# Lambda reaches its kube-apiserver through a tunnel/ingress. The bearer token
# is for a dedicated "makeway-worker" ServiceAccount bound to a minimal RBAC
# Role (create/get Claims, get Secrets, manage the {claim}-creds Secret).
KUBE_API_ENDPOINT = os.environ["KUBE_API_ENDPOINT"].rstrip("/")
KUBE_CA_CERT = os.environ.get("KUBE_CA_CERT", "")  # base64 CA bundle, else verify disabled
KUBE_TOKEN = os.environ["KUBE_TOKEN"]

# --- GitHub (platform repo hosting gitops) -----------------------------------
GITHUB_OWNER = os.environ["GITHUB_OWNER"]
GITHUB_TOKEN_SECRET_ID = os.environ["GITHUB_TOKEN_SECRET_ID"]
MAKEWAY_PLATFORM_REPO = os.environ.get("MAKEWAY_PLATFORM_REPO", "Makeway-IDP")
PLATFORM_REPO = f"{GITHUB_OWNER}/{MAKEWAY_PLATFORM_REPO}"

# --- Provisioning knobs -------------------------------------------------------
STEP = "provision_infra"
SECRETS_PREFIX = os.environ.get("SECRETS_PREFIX", "makeway")
# SSM parameter holding the platform VPC facts JSON the database claims need
# ({vpcId, subnetIds, cidr}) — read per apply, see _platform_vpc().
PLATFORM_VPC_PARAMETER = os.environ["PLATFORM_VPC_PARAMETER"]
# DB ingress: an empty env derives from the platform VPC CIDR published in SSM
# (right where pods run in-VPC — EKS). Local-cluster seam: pods run off-VPC, so
# RDS_PUBLICLY_ACCESSIBLE=true + RDS_INGRESS_CIDR = the machine's public IP.
RDS_PUBLICLY_ACCESSIBLE = os.environ.get("RDS_PUBLICLY_ACCESSIBLE", "true").lower() == "true"
RDS_INGRESS_CIDR = os.environ.get("RDS_INGRESS_CIDR", "")
CONN_SECRET_SUFFIX = "-connection-details"

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claim_templates")

# Capability type discriminators (dto/enums/capability_types.py).
REL_DATABASE = "rel_database"
STORAGE = "storage"
MESSAGING = "messaging"

# requestType values the control plane exposes on the request-details payload;
# apply/check/extract branch on them for teardown runs.
REQUEST_TYPE_DELETE = "delete_app"
REQUEST_TYPE_UPDATE = "update_app"

# Capability types whose XR instances back onto the AWS API directly (S3/SQS/SNS).
# Pods on the local cluster have no IRSA, so extract provisions a scoped IAM
# user + access keys for these.
AWS_API_CAPABILITIES = {STORAGE, MESSAGING}

_iam = boto3.client("iam", region_name=REGION)
_secretsmanager = boto3.client("secretsmanager", region_name=REGION)
_sts = boto3.client("sts", region_name=REGION)
_secrets_client = boto3.client("secretsmanager", region_name=REGION)
_ssm = boto3.client("ssm", region_name=REGION)
_github_token_cache: str | None = None
_git_identity_cache: dict | None = None
_account_id_cache: str | None = None
_platform_vpc_cache: dict | None = None


def _platform_vpc() -> dict:
    """Platform VPC facts ({vpcId, subnetIds, cidr}) for database claims.

    Published by the platform root's Terraform (aws_ssm_parameter.platform_vpc,
    name from PLATFORM_VPC_PARAMETER). Replaces the values the old
    argocd/crossplane-overlays kustomize overlay baked in from git — a rebuilt
    platform VPC now propagates on the next provision, no repo edit. Cached
    per warm container like _account_id().
    """
    global _platform_vpc_cache
    if _platform_vpc_cache is None:
        raw = _ssm.get_parameter(Name=PLATFORM_VPC_PARAMETER)["Parameter"]["Value"]
        facts = json.loads(raw)
        _platform_vpc_cache = {
            "vpc_id": facts["vpcId"],
            "subnet_ids": list(facts["subnetIds"]),
            "cidr": facts["cidr"],
        }
    return _platform_vpc_cache


# --------------------------------------------------------------------------- #
# Low-level HTTP helpers (stdlib only — no `requests` in the Lambda)
# --------------------------------------------------------------------------- #

def _http(method: str, url: str, payload=None, headers=None, timeout: int = 60):
    data = None
    request_headers = {"User-Agent": "makeway-worker"}
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
# Control-plane status callbacks
# --------------------------------------------------------------------------- #

def _report(
    request_id: int,
    job_id: int,
    status: str,
    execution_arn: str | None = None,
    error: str | None = None,
    capabilities: list | None = None,
) -> None:
    payload = {
        "jobId": job_id,
        "step": STEP,
        "status": status,
    }
    if execution_arn:
        payload["executionArn"] = execution_arn
    if error:
        payload["error"] = error
    if capabilities:
        payload["capabilities"] = capabilities
    _control_plane("POST", f"/internal/requests/{request_id}/status", payload)
    logger.info("reported %s for request_id=%s job_id=%s", status, request_id, job_id)


# --------------------------------------------------------------------------- #
# Kubernetes API access (stdlib HTTPS + bearer token)
# --------------------------------------------------------------------------- #

_kube_ssl_contexts: dict[str, ssl.SSLContext] = {}


def _kube_ssl_context(ca_cert: str | None = None) -> ssl.SSLContext:
    """SSL context for a kube-apiserver call, cached per CA bundle.

    Accepts an optional per-cluster CA (from the claim / control-plane
    registry); when absent it falls back to the module global KUBE_CA_CERT.
    A populated CA enables real verification. An empty CA (the dev-tunnel
    convention — see localTunnel/README.md) disables verification with a
    loud warning; the bearer token is still the auth boundary. One
    no-verify context is shared under the empty-CA key.
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
    content_type: str = "application/json",
    *,
    endpoint: str | None = None,
    token: str | None = None,
    ca_cert: str | None = None,
):
    """Raw call to a (exposed) kube-apiserver. Returns (status, body).

    ``endpoint``/``token``/``ca_cert`` override the module globals — per-claim
    cluster selection sourced from the control-plane registry. None falls back
    to KUBE_API_ENDPOINT / KUBE_TOKEN / KUBE_CA_CERT.
    """
    api_endpoint = (endpoint or KUBE_API_ENDPOINT).rstrip("/")
    api_token = token or KUBE_TOKEN
    url = f"{api_endpoint}{path}"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
        "Content-Type": content_type,
        # Tunnel edges (loca.lt) serve a consent page to browser-looking
        # traffic; explicit bypass keeps API calls clean on such endpoints.
        "Bypass-Tunnel-Reminder": "true",
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


def _kube_upsert(
    collection: str,
    name: str,
    manifest: dict,
    *,
    endpoint: str | None = None,
    token: str | None = None,
    ca_cert: str | None = None,
) -> None:
    """Create-or-update a namespaced object. Idempotent (merge-patch on 200)."""
    item = f"{collection}/{name}"
    status, _body = _kube("GET", item, endpoint=endpoint, token=token, ca_cert=ca_cert)
    if status == 404:
        status, body = _kube(
            "POST", collection, manifest, endpoint=endpoint, token=token, ca_cert=ca_cert
        )
    else:
        status, body = _kube(
            "PATCH", item, manifest, content_type="application/merge-patch+json",
            endpoint=endpoint, token=token, ca_cert=ca_cert,
        )
    if not 200 <= status < 300:
        detail = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)
        raise RuntimeError(f"kube {collection}/{name} -> HTTP {status}: {detail}")


def _kube_get(
    collection: str,
    name: str,
    *,
    endpoint: str | None = None,
    token: str | None = None,
    ca_cert: str | None = None,
) -> tuple[int, dict | None]:
    return _kube(
        "GET", f"{collection}/{name}", endpoint=endpoint, token=token, ca_cert=ca_cert
    )


def _kube_delete(
    collection: str,
    name: str,
    *,
    endpoint: str | None = None,
    token: str | None = None,
    ca_cert: str | None = None,
) -> tuple[int, dict | None]:
    """Delete a namespaced object; a 404 is a successful no-op. Returns status.

    Deleting an XR instance makes Crossplane tear its composed AWS resources
    down; the object stays with a deletionTimestamp until it finalizes, which
    ``_check``'s teardown branch polls to a 404.
    """
    status, body = _kube(
        "DELETE",
        f"{collection}/{name}",
        endpoint=endpoint,
        token=token,
        ca_cert=ca_cert,
    )
    if status == 404:
        return status, body
    if not 200 <= status < 300:
        detail = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)
        raise RuntimeError(f"kube DELETE {collection}/{name} -> HTTP {status}: {detail}")
    return status, body


def _gone(status: int) -> bool:
    """404 = the object is gone (a deleted XR reads back as 404)."""
    return status == 404


# --------------------------------------------------------------------------- #
# Claim expansion — one capability -> one or more Crossplane XR instances
# --------------------------------------------------------------------------- #


def _slug(value: str) -> str:
    """DNS-safe lower-case slug for XR instance names / SM secret names.
    
    Example : 'My Python App' -> 'my-python-app'
    """
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "default"


def _render(text: str, **tokens: str) -> str:
    for key, value in tokens.items():
        text = text.replace(f"__{key}__", value)
    return text


def _account_id() -> str:
    global _account_id_cache
    if _account_id_cache is None:
        _account_id_cache = _sts.get_caller_identity()["Account"]
    return _account_id_cache


def _claims_for(app_name: str, capability: dict, account_id: str) -> list[dict]:
    """Expand a capability into the Crossplane XR instances it needs.

    Each claim dict carries everything apply/check/extract need: the template
    name, the deterministic claim name / namespace / connection secret name, the
    render tokens, whether pods need AWS API credentials, and the Secrets
    Manager secret name the credentials will be mirrored into.
    """
    cap_type = capability["capabilityType"]
    config = capability.get("config") or {}
    namespace = capability["namespace"]
    env = capability.get("environment") or "qa"
    region = config.get("region") or DEFAULT_REGION
    cap_id = str(capability["capabilityId"])
    # Per-capability cluster access, from the control-plane registry. None on
    # any of these means "use the Lambda env KUBE_* fallback" downstream.
    kube_endpoint = capability.get("kubeApiEndpoint")
    kube_token = capability.get("kubeToken")
    kube_ca_cert = capability.get("kubeCaCert")

    claims: list[dict] = []

    if cap_type == REL_DATABASE:
        db_name = config.get("name") or "db"
        slug = _slug(db_name)
        claim_name = f"{app_name}-{env}-{slug}"
        claims.append(
            _claim(
                slug=slug,
                template="relational-database.yaml",
                claim_name=claim_name,
                namespace=namespace,
                capability_id=cap_id,
                aws_api=False,
                environment=env,
                kube_endpoint=kube_endpoint,
                kube_token=kube_token,
                kube_ca_cert=kube_ca_cert,
                tokens={
                    "APP_NAME": app_name,
                    "ENV": env,
                    "DB_NAME": db_name,
                    "MASTER_USERNAME": config.get("username") or "makeway_admin",
                    "CAPACITY": str(config.get("capacity") or 5),
                    "REGION": region,
                    "PUBLICLY_ACCESSIBLE": "true" if RDS_PUBLICLY_ACCESSIBLE else "false",
                    "INGRESS_CIDR": RDS_INGRESS_CIDR or _platform_vpc()["cidr"],
                    # Platform placement facts, read from SSM (never committed
                    # to git) — fill the claim parameters the Composition
                    # patches into the DBSubnetGroup / SecurityGroup.
                    "PLATFORM_VPC_ID": _platform_vpc()["vpc_id"],
                    "PLATFORM_PRIVATE_SUBNET_1": _platform_vpc()["subnet_ids"][0],
                    "PLATFORM_PRIVATE_SUBNET_2": _platform_vpc()["subnet_ids"][1],
                },
            )
        )

    elif cap_type == STORAGE:
        s3 = config.get("s3") or {}
        slug = "storage"
        claim_name = f"{app_name}-{env}-{slug}"
        # {app}-{env}-storage — deterministic + globally unique. S3 names are
        # capped at 63 chars; clamp from the front (keep the app prefix).
        bucket = claim_name[:63]
        claims.append(
            _claim(
                slug=slug,
                template="object-storage.yaml",
                claim_name=claim_name,
                namespace=namespace,
                capability_id=cap_id,
                aws_api=True,
                environment=env,
                kube_endpoint=kube_endpoint,
                kube_token=kube_token,
                kube_ca_cert=kube_ca_cert,
                tokens={
                    "APP_NAME": app_name,
                    "ENV": env,
                    "BUCKET_NAME": bucket,
                    "REGION": s3.get("region") or DEFAULT_REGION,
                    "CLOUDFRONT": "true" if s3.get("cloudfront") else "false",
                },
            )
        )

    elif cap_type == MESSAGING:
        for queue in config.get("queue") or []:
            queue_name = queue.get("name") or "default"
            slug = _slug(queue_name)
            claim_name = f"{app_name}-{env}-{slug}"
            dlq_arn = (
                f"arn:aws:sqs:{region}:{account_id}:{queue_name}-dlq"
            )
            claims.append(
                _claim(
                    slug=slug,
                    template="message-queue.yaml",
                    claim_name=claim_name,
                    namespace=namespace,
                    capability_id=cap_id,
                    aws_api=True,
                    environment=env,
                    kube_endpoint=kube_endpoint,
                    kube_token=kube_token,
                    kube_ca_cert=kube_ca_cert,
                    tokens={
                        "APP_NAME": app_name,
                        "ENV": env,
                        "QUEUE_NAME": queue_name,
                        "REGION": region,
                        "DLQ_ARN": dlq_arn,
                    },
                )
            )
        if config.get("notification"):
            slug = "notification"
            claim_name = f"{app_name}-{env}-{slug}"
            claims.append(
                _claim(
                    slug=slug,
                    template="notification-topic.yaml",
                    claim_name=claim_name,
                    namespace=namespace,
                    capability_id=cap_id,
                    aws_api=True,
                    environment=env,
                    kube_endpoint=kube_endpoint,
                    kube_token=kube_token,
                    kube_ca_cert=kube_ca_cert,
                    tokens={
                        "APP_NAME": app_name,
                        "ENV": env,
                        "TOPIC_NAME": claim_name,
                        "REGION": region,
                    },
                )
            )

    else:
        logger.warning("unknown capability type %s — skipping", cap_type)

    return claims


def _claim(
    slug: str,
    template: str,
    claim_name: str,
    namespace: str,
    capability_id: str,
    aws_api: bool,
    tokens: dict,
    *,
    environment: str | None = None,
    kube_endpoint: str | None = None,
    kube_token: str | None = None,
    kube_ca_cert: str | None = None,
) -> dict:
    tokens = dict(tokens)
    tokens.update(
        {
            "CLAIM_NAME": claim_name,
            "NAMESPACE": namespace,
            "CONN_SECRET": f"{claim_name}{CONN_SECRET_SUFFIX}",
            "CAPABILITY_ID": capability_id,
        }
    )
    return {
        "slug": slug,
        "template": template,
        "claim_name": claim_name,
        "namespace": namespace,
        "conn_secret": f"{claim_name}{CONN_SECRET_SUFFIX}",
        "tokens": tokens,
        "aws_api": aws_api,
        "sm_name": f"{SECRETS_PREFIX}/{tokens['APP_NAME']}/{tokens['ENV']}/{slug}",
        "capability_id": capability_id,
        # Per-claim cluster selection (from the capability's Cluster registry
        # row). None = fall back to the module KUBE_* globals in _kube.
        "environment": environment,
        "kube_endpoint": kube_endpoint,
        "kube_token": kube_token,
        "kube_ca_cert": kube_ca_cert,
    }


def _claim_kube(claim: dict) -> tuple[str | None, str | None, str | None]:
    """Per-claim kube access (endpoint, token, CA); None/absent => globals."""
    return (
        claim.get("kube_endpoint"),
        claim.get("kube_token"),
        claim.get("kube_ca_cert"),
    )


def _claim_manifest(claim: dict) -> dict:
    """Render the claim's YAML template and parse it back into a manifest dict."""
    with open(
        os.path.join(TEMPLATES_DIR, claim["template"]), "r", encoding="utf-8"
    ) as handle:
        rendered = _render(handle.read(), **claim["tokens"])
    return _parse_claim_yaml(rendered)


def _parse_claim_yaml(text: str) -> dict:
    def scalar(value: str):
        value = value.strip()
        if value == "":
            return None
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            return value[1:-1]
        if value in ("true", "True"):
            return True
        if value in ("false", "False"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        return value

    stripped = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    lines = []
    for line in stripped:
        leading = len(line) - len(line.lstrip(" "))
        lines.append((leading, line.lstrip(" ")))

    cursor = 0

    def parse(indent: int) -> dict:
        nonlocal cursor
        result = {}
        while cursor < len(lines):
            current_indent, line = lines[cursor]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"unexpected indentation: {line!r}")
            if ":" not in line:
                raise ValueError(f"expected 'key: value', got {line!r}")
            key, _, value = line.partition(":")
            key = key.strip()
            if value.strip() == "":
                cursor += 1
                # Block list ("- item") under this key, items at indent+2 — the
                # only sequences claim templates use (platformSubnetIds).
                if (
                    cursor < len(lines)
                    and lines[cursor][0] == indent + 2
                    and lines[cursor][1].startswith("- ")
                ):
                    items = []
                    while (
                        cursor < len(lines)
                        and lines[cursor][0] == indent + 2
                        and lines[cursor][1].startswith("- ")
                    ):
                        items.append(scalar(lines[cursor][1][2:]))
                        cursor += 1
                    result[key] = items
                    continue
                child = parse(indent + 2)
                result[key] = child if child else None
                continue
            result[key] = scalar(value)
            cursor += 1
        return result

    return parse(0)


# --------------------------------------------------------------------------- #
# Removal bookkeeping (env-scoped delete + update-embedded removals)
# --------------------------------------------------------------------------- #

def _removed_capability_keys(details: dict) -> set[tuple[str | None, str]]:
    """``(environment, capabilityType)`` pairs this run must tear down.

    ``delete_app``: every capability scoped to the rawRequest env is a teardown
    target (their rows still exist — the control plane purges them on SUCCESS).
    ``update_app``: the entries' ``remove_capabilities`` type lists. Anything
    else (a create, an update without removals) returns an empty set.
    """
    request_type = details.get("requestType")
    raw = details.get("rawRequest") or {}
    removed: set[tuple[str | None, str]] = set()
    if request_type == REQUEST_TYPE_DELETE:
        env = raw.get("env")
        if env:
            removed = {
                (cap.get("environment"), cap.get("capabilityType"))
                for cap in details.get("capabilities") or []
                if cap.get("environment") == env
            }
    elif request_type == REQUEST_TYPE_UPDATE:
        for entry in raw.get("updates") or []:
            env = entry.get("env")
            for cap_type in entry.get("remove_capabilities") or []:
                removed.add((env, cap_type))
    return removed


def _capability_is_removed(cap: dict, removed: set[tuple[str | None, str]]) -> bool:
    return (cap.get("environment"), cap.get("capabilityType")) in removed


# --------------------------------------------------------------------------- #
# Apply action
# --------------------------------------------------------------------------- #

def _ensure_namespace(claim: dict) -> None:
    """Idempotently ensure the claim's namespace exists before applying.

    The namespace normally arrives via gitops (Step-1's PR -> ArgoCD sync of
    base/namespaces.yaml), but Step-2 runs immediately after Step-1 — long
    before that side lands — and a missing namespace fails the apply's first
    upsert with "namespaces not found". Create it here; ArgoCD later adopts
    it from gitops. Never deletes: teardown stays ArgoCD's (see _delete_claim).
    """
    namespace = claim["namespace"]
    endpoint, token, ca_cert = _claim_kube(claim)
    status, body = _kube_get(
        "/api/v1/namespaces", namespace, endpoint=endpoint, token=token, ca_cert=ca_cert
    )
    if status == 200:
        return
    if status != 404:
        detail = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)
        raise RuntimeError(f"kube namespaces/{namespace} -> HTTP {status}: {detail}")
    status, body = _kube(
        "POST",
        "/api/v1/namespaces",
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": namespace, "labels": {"managed-by": "makeway"}},
        },
        endpoint=endpoint,
        token=token,
        ca_cert=ca_cert,
    )
    if status == 409:
        # A concurrent creator (e.g. ArgoCD) won the race — it exists now.
        return
    if not 200 <= status < 300:
        detail = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)
        raise RuntimeError(f"kube POST namespaces/{namespace} -> HTTP {status}: {detail}")
    logger.info("created namespace %s (gitops side had not landed yet)", namespace)


def _apply_claim(claim: dict) -> None:
    _ensure_namespace(claim)
    namespace = claim["namespace"]
    manifest = _claim_manifest(claim)
    endpoint, token, ca_cert = _claim_kube(claim)

    # RDS master password: generate once and store in {claimName}-creds before
    # the XR instance is applied (the Composition's passwordSecretRef references
    # it and the Lambda reads it back during extract).
    if claim["template"] == "relational-database.yaml":
        creds = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": f"{claim['claim_name']}-creds",
                "namespace": namespace,
                "labels": {"managed-by": "makeway"},
            },
            "type": "Opaque",
            "stringData": {"password": secrets.token_urlsafe(24)},
        }
        _kube_upsert(
            f"/api/v1/namespaces/{namespace}/secrets",
            f"{claim['claim_name']}-creds",
            creds,
            endpoint=endpoint,
            token=token,
            ca_cert=ca_cert,
        )

    kind = manifest["kind"].lower()
    plural = kind + "s"
    _kube_upsert(
        f"/apis/makeway.io/v1beta1/namespaces/{namespace}/{plural}",
        claim["claim_name"],
        manifest,
        endpoint=endpoint,
        token=token,
        ca_cert=ca_cert,
    )
    logger.info("applied %s instance %s/%s", kind, namespace, claim["claim_name"])


# --------------------------------------------------------------------------- #
# Teardown — delete XR instances + credential artifacts
# --------------------------------------------------------------------------- #

def _claim_iam_user(claim: dict) -> str:
    """The IAM user name ``_ensure_aws_identity`` created for this claim."""
    return (
        f"makeway-{claim['tokens']['APP_NAME']}-{claim['tokens']['ENV']}-{claim['slug']}"
    )[:64]


def _delete_claim(claim: dict) -> None:
    """Delete one XR instance and its apply-time ``{claim}-creds`` Secret.

    Deleting the XR makes Crossplane tear the composed AWS resources down as it
    finalizes; the namespace itself is ArgoCD's (the env overlay removal
    cascades it) — the worker never deletes namespaces. Update removals clean
    their credential artifacts per claim here; an env delete sweeps the rest.
    """
    kind = _claim_kind(claim)
    plural = kind.lower() + "s"
    endpoint, token, ca_cert = _claim_kube(claim)
    _kube_delete(
        f"/apis/makeway.io/v1beta1/namespaces/{claim['namespace']}/{plural}",
        claim["claim_name"],
        endpoint=endpoint,
        token=token,
        ca_cert=ca_cert,
    )
    _kube_delete(
        f"/api/v1/namespaces/{claim['namespace']}/secrets",
        f"{claim['claim_name']}-creds",
        endpoint=endpoint,
        token=token,
        ca_cert=ca_cert,
    )
    _delete_claim_credentials(claim)
    logger.info("deleted %s instance %s/%s", kind, claim["namespace"], claim["claim_name"])


def _delete_claim_credentials(claim: dict) -> None:
    """Best-effort removal of a claim's Secrets Manager secret + IAM user.

    The Crossplane teardown owns the AWS resources; these are just the
    credential artifacts extract created. Failures are logged, not raised — a
    lingering secret must not fail the teardown."""
    try:
        _secretsmanager.delete_secret(
            SecretId=claim["sm_name"], ForceDeleteWithoutRecovery=True
        )
        logger.info("deleted secret %s", claim["sm_name"])
    except _secretsmanager.exceptions.ResourceNotFoundException:
        pass
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup
        logger.warning("SM cleanup skipped for %s: %s", claim["sm_name"], exc)
    _iam_delete_user(_claim_iam_user(claim))


def _iam_delete_user(user_name: str) -> None:
    """Best-effort delete of one claim's IAM user (keys + inline policy first)."""
    try:
        for key in _iam.list_access_keys(UserName=user_name)["AccessKeyMetadata"]:
            _iam.delete_access_key(UserName=user_name, AccessKeyId=key["AccessKeyId"])
        for policy in _iam.list_user_policies(UserName=user_name)["PolicyNames"]:
            _iam.delete_user_policy(UserName=user_name, PolicyName=policy)
        _iam.delete_user(UserName=user_name)
        logger.info("deleted IAM user %s", user_name)
    except _iam.exceptions.NoSuchEntityException:
        pass
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup
        logger.warning("IAM cleanup skipped for %s: %s", user_name, exc)


def _sm_delete_prefix(prefix: str) -> None:
    """Best-effort delete of every Makeway secret under ``prefix``.

    ``ForceDeleteWithoutRecovery`` skips the recovery window — these are
    generated capability credentials, not human-held secrets."""
    try:
        paginator = _secretsmanager.get_paginator("list_secrets")
        for page in paginator.paginate(Filters=[{"Key": "name", "Values": [prefix]}]):
            for secret in page.get("SecretList", []):
                name = secret["Name"]
                if not name.startswith(prefix):
                    continue
                try:
                    _secretsmanager.delete_secret(
                        SecretId=name, ForceDeleteWithoutRecovery=True
                    )
                    logger.info("deleted secret %s", name)
                except Exception as exc:  # noqa: BLE001 — best-effort
                    logger.warning("secret cleanup skipped for %s: %s", name, exc)
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup
        logger.warning("secret-prefix cleanup skipped for %s: %s", prefix, exc)


def _iam_delete_users_by_prefix(prefix: str) -> None:
    """Best-effort delete of every IAM user extract created for one env."""
    try:
        paginator = _iam.get_paginator("list_users")
        for page in paginator.paginate():
            for user in page.get("Users", []):
                if user["UserName"].startswith(prefix):
                    _iam_delete_user(user["UserName"])
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup
        logger.warning("IAM env cleanup skipped for %s*: %s", prefix, exc)


def _apply(request_id: int, job_id: int, execution_arn: str | None, event: dict) -> dict:
    details = _control_plane("GET", f"/internal/requests/{request_id}")
    if details.get("job", {}).get("status") == "success":
        logger.info("request_id=%s job already SUCCESS — skipping Step 2 apply", request_id)
        # This output feeds the state machine's Check loop, whose payload
        # references $.request_id / $.job_id / $.attempt — a bare skipped dict
        # would fail the state machine. attempt: 1 lets the (idempotent)
        # Wait/Check/Extract chain run to completion.
        return {
            "status": "skipped",
            "reason": "already_success",
            "request_id": request_id,
            "job_id": job_id,
            "attempt": 1,
        }

    _report(request_id, job_id, "in_progress", execution_arn)

    app_name = details["app"]["appName"]
    account_id = _account_id()
    removed = _removed_capability_keys(details)

    # Mixed mode (update with removals): kept capabilities upsert as today,
    # removal targets are deleted instead. A plain create/delete splits the
    # same way — every claim on one side.
    kept_claims = []
    removed_claims = []
    for cap in details.get("capabilities") or []:
        claims = _claims_for(app_name, cap, account_id)
        if _capability_is_removed(cap, removed):
            removed_claims.extend(claims)
        else:
            kept_claims.extend(claims)

    for claim in kept_claims:
        _apply_claim(claim)

    deleted = [claim["claim_name"] for claim in removed_claims]
    for claim in removed_claims:
        _delete_claim(claim)

    # Env-scoped teardown: one sweep for the credentials extract created for
    # the whole env (update removals already cleaned theirs per claim).
    if details.get("requestType") == REQUEST_TYPE_DELETE:
        env = (details.get("rawRequest") or {}).get("env")
        if env:
            _sm_delete_prefix(f"{SECRETS_PREFIX}/{app_name}/{env}/")
            _iam_delete_users_by_prefix(f"makeway-{app_name}-{env}-")

    return {
        "status": "applied",
        "request_id": request_id,
        "job_id": job_id,
        "claim_count": len(kept_claims),
        "deleted": deleted,
        # Seeds the state-machine Check loop's attempt counter (see the ASL).
        "attempt": 1,
    }


# --------------------------------------------------------------------------- #
# Check action — are all XR instances Ready + Synced?
# --------------------------------------------------------------------------- #

def _claim_status(body: dict | None) -> tuple[bool, bool]:
    ready = False
    synced = False
    for condition in (body or {}).get("status", {}).get("conditions", []) or []:
        if condition.get("type") == "Ready" and condition.get("status") == "True":
            ready = True
        if condition.get("type") == "Synced" and condition.get("status") == "True":
            synced = True
    return ready, synced


def _check(request_id: int, job_id: int, execution_arn: str | None, event: dict) -> dict:
    attempt = int(event.get("attempt", 1))
    details = _control_plane("GET", f"/internal/requests/{request_id}")
    app_name = details["app"]["appName"]
    account_id = _account_id()
    removed = _removed_capability_keys(details)

    pending = []
    for cap in details.get("capabilities") or []:
        is_removed = _capability_is_removed(cap, removed)
        for claim in _claims_for(app_name, cap, account_id):
            kind = _claim_kind(claim)
            # XR kinds are CamelCase ("RelationalDatabase"); the API plural is
            # the lowercase kind + "s" ("relationaldatabases").
            plural = kind.lower() + "s"
            endpoint, token, ca_cert = _claim_kube(claim)
            status, body = _kube_get(
                f"/apis/makeway.io/v1beta1/namespaces/{claim['namespace']}/{plural}",
                claim["claim_name"],
                endpoint=endpoint,
                token=token,
                ca_cert=ca_cert,
            )
            if is_removed:
                # Teardown target: gone (404) means done — anything else is
                # still terminating while Crossplane tears the AWS resources
                # down (or ArgoCD cascades the namespace away).
                if not _gone(status):
                    pending.append(claim["claim_name"])
                continue
            if status == 404:
                pending.append(claim["claim_name"])
                continue
            if not 200 <= status < 300:
                pending.append(claim["claim_name"])
                logger.warning(
                    "check %s/%s -> HTTP %s (treated as not ready)",
                    claim["namespace"],
                    claim["claim_name"],
                    status,
                )
                continue
            ready, synced = _claim_status(body)
            if not (ready and synced):
                pending.append(claim["claim_name"])

    logger.info(
        "check request_id=%s attempt=%s pending=%s",
        request_id,
        attempt,
        pending,
    )
    return {
        "ready": not pending,
        "pending": pending,
        "attempt": attempt,
        "request_id": request_id,
        "job_id": job_id,
    }


def _claim_kind(claim: dict) -> str:
    # v2 XR kinds (Claims were removed in Crossplane v2 — the XR is the resource
    # the worker applies and polls directly).
    template_kinds = {
        "relational-database.yaml": "RelationalDatabase",
        "object-storage.yaml": "ObjectStorage",
        "message-queue.yaml": "MessageQueue",
        "notification-topic.yaml": "NotificationTopic",
    }
    return template_kinds[claim["template"]]


# --------------------------------------------------------------------------- #
# Extract action — mirror credentials, provision AWS API identity, gitops
# --------------------------------------------------------------------------- #

def _read_connection_secret(claim: dict) -> dict:
    """Read the XR instance's connection Secret (written by the function) as str values."""
    endpoint, token, ca_cert = _claim_kube(claim)
    status, body = _kube_get(
        f"/api/v1/namespaces/{claim['namespace']}/secrets",
        claim["conn_secret"],
        endpoint=endpoint,
        token=token,
        ca_cert=ca_cert,
    )
    if not 200 <= status < 300:
        raise RuntimeError(
            f"connection secret {claim['conn_secret']}/{claim['namespace']} "
            f"-> HTTP {status}"
        )
    data = (body or {}).get("data") or {}
    return {
        key: base64.b64decode(value).decode("utf-8")
        for key, value in data.items()
        if isinstance(value, str)
    }


def _aws_policy(claim: dict, conn: dict) -> dict:
    """Least-privilege inline policy for the AWS API the claim backs onto."""
    slug = claim["slug"]
    if slug == "storage":
        bucket = conn.get("bucketName") or f"{claim['claim_name']}"
        resources = [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"]
        actions = [
            "s3:ListBucket",
            "s3:GetBucketLocation",
            "s3:GetObject",
            "s3:PutObject",
            "s3:DeleteObject",
        ]
    elif slug == "notification":
        resources = [conn["topicArn"]]
        actions = ["sns:Publish"]
    else:  # queue (incl. DLQ)
        resources = [conn.get("queueArn"), conn.get("dlqArn")]
        actions = [
            "sqs:SendMessage",
            "sqs:ReceiveMessage",
            "sqs:DeleteMessage",
            "sqs:ChangeMessageVisibility",
            "sqs:GetQueueUrl",
            "sqs:GetQueueAttributes",
        ]
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": actions,
                "Resource": [r for r in resources if r],
            }
        ],
    }


def _ensure_aws_identity(app_name: str, env: str, claim: dict, conn: dict) -> dict:
    """Create/reuse a scoped IAM user + access keys for an AWS-API capability.

    Local cluster has no IRSA, so pods authenticate to AWS with static keys. One
    user per claim (``makeway-{app}-{env}-{slug}``) with an inline policy scoped
    to exactly the resources this capability backs onto.

    Idempotency: access keys are reused when they already exist. AWS only
    returns a secret key once, so on reuse the caller must preserve the existing
    Secrets Manager value (see ``_sm_merge_secret``) rather than overwrite it.
    """
    user_name = f"makeway-{app_name}-{env}-{claim['slug']}"[:64]

    try:
        _iam.get_user(UserName=user_name)
    except _iam.exceptions.NoSuchEntityException:
        _iam.create_user(
            UserName=user_name,
            Tags=[
                {"Key": "managed-by", "Value": "makeway"},
                {"Key": "app", "Value": app_name},
                {"Key": "environment", "Value": env},
            ],
        )
        logger.info("created IAM user %s", user_name)

    policy = _aws_policy(claim, conn)
    _iam.put_user_policy(
        UserName=user_name,
        PolicyName="makeway",
        PolicyDocument=json.dumps(policy),
    )

    existing = _iam.list_access_keys(UserName=user_name)["AccessKeyMetadata"]
    if existing:
        access_key_id = existing[0]["AccessKeyId"]
        logger.info("reusing access key %s for %s", access_key_id, user_name)
        return {"aws_access_key_id": access_key_id}

    created = _iam.create_access_key(UserName=user_name)["AccessKey"]
    logger.info("created access key %s for %s", created["AccessKeyId"], user_name)
    return {
        "aws_access_key_id": created["AccessKeyId"],
        "aws_secret_access_key": created["SecretAccessKey"],
    }


def _sm_merge_secret(name: str, value: dict) -> str:
    """Create-or-update a Secrets Manager secret, merging into the existing one.

    Merging matters for idempotency: on a retry the IAM access key already
    exists, so ``value`` carries only its id — overwriting would drop the stored
    secret key AWS returned only once. Returns the secret's ARN.
    """
    try:
        existing = _secretsmanager.get_secret_value(SecretId=name)
        base = json.loads(existing["SecretString"])
    except _secretsmanager.exceptions.ResourceNotFoundException:
        base = {}
    base.update(value)

    try:
        _secretsmanager.create_secret(
            Name=name,
            Description="Makeway capability credentials (managed by Step 2).",
            Tags=[{"Key": "managed-by", "Value": "makeway"}],
        )
    except _secretsmanager.exceptions.ResourceExistsException:
        pass

    arn = _secretsmanager.describe_secret(SecretId=name)["ARN"]
    _secretsmanager.put_secret_value(
        SecretId=arn,
        SecretString=json.dumps(base, indent=2),
    )
    return arn


def _github_token() -> str:
    global _github_token_cache
    if _github_token_cache is None:
        secret = _secrets_client.get_secret_value(SecretId=GITHUB_TOKEN_SECRET_ID)
        _github_token_cache = secret["SecretString"].strip()
    return _github_token_cache


def _git_identity() -> dict:
    global _git_identity_cache
    if _git_identity_cache is None:
        user = _gh("GET", "/user")
        login = user["login"]
        _git_identity_cache = {
            "name": user.get("name") or login,
            "email": f"{user['id']}+{login}@users.noreply.github.com",
        }
    return _git_identity_cache


def _gh(method: str, path: str, payload=None, params: dict | None = None):
    url = f"https://api.github.com{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    status, body = _http(
        method,
        url,
        payload,
        {
            "Authorization": f"Bearer {_github_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if not 200 <= status < 300:
        detail = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)
        raise RuntimeError(f"github {method} {path} -> HTTP {status}: {detail}")
    return body


def _git_get_file(repo: str, path: str) -> str | None:
    """Content of a file on the repo's default branch, or None if absent."""
    status, body = _http(
        "GET",
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers={
            "Authorization": f"Bearer {_github_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if status == 404:
        return None
    if not 200 <= status < 300:
        raise RuntimeError(f"github GET contents/{path} -> HTTP {status}")
    return base64.b64decode(body["content"]).decode("utf-8")


def _git_upsert_files(repo: str, files: dict[str, str], message: str) -> bool:
    """Create-or-overwrite ``files`` ({path: content}) on the repo's main branch.

    Unlike Step-1's ``_push_tree`` (create-only), this overwrites existing blobs
    — needed to append resources to an env kustomization. Idempotent: unchanged
    content is skipped by diffing against the current tree.
    """
    ref = _gh("GET", f"/repos/{repo}/git/refs/heads/main")
    head_sha = ref["object"]["sha"]
    current_tree = _gh(
        "GET", f"/repos/{repo}/git/trees/{head_sha}", params={"recursive": "1"}
    )
    current_blobs = {
        entry["path"]: entry["sha"]
        for entry in current_tree["tree"]
        if entry.get("type") == "blob"
    }

    new_blobs = {}
    for path, content in files.items():
        if current_blobs.get(path) is not None:
            blob = _gh(
                "POST",
                f"/repos/{repo}/git/blobs",
                {"content": content, "encoding": "utf-8"},
            )
            # Skip when the blob already holds identical content.
            if blob["sha"] == current_blobs[path]:
                continue
            new_blobs[path] = blob["sha"]
        else:
            blob = _gh(
                "POST",
                f"/repos/{repo}/git/blobs",
                {"content": content, "encoding": "utf-8"},
            )
            new_blobs[path] = blob["sha"]

    if not new_blobs:
        logger.info("[%s] no changes to push — gitops already at desired state", repo)
        return False

    tree_entries = [
        {"path": path, "mode": "100644", "type": "blob", "sha": sha}
        for path, sha in new_blobs.items()
    ]
    new_tree = _gh(
        "POST",
        f"/repos/{repo}/git/trees",
        {"base_tree": current_tree["sha"], "tree": tree_entries},
    )
    identity = _git_identity()
    commit = _gh(
        "POST",
        f"/repos/{repo}/git/commits",
        {
            "message": message,
            "tree": new_tree["sha"],
            "parents": [head_sha],
            "author": identity,
            "committer": identity,
        },
    )
    _gh(
        "PATCH",
        f"/repos/{repo}/git/refs/heads/main",
        {"sha": commit["sha"]},
    )
    logger.info("[%s] pushed %d files (%s)", repo, len(new_blobs), message)
    return True


def _add_kustomization_resource(current: str, resource_line: str) -> str:
    """Insert ``  - <resource_line>`` into an env kustomization's resources list.

    The generated kustomization lists ``../../base`` + ``../../apps/*`` under
    ``resources:`` and ``- path: ...`` entries under ``patches:``. ExternalSecret
    files go into a sibling ``external-secrets/`` dir, so the new line is added
    just before the ``patches:`` block (idempotent — a repeated line is a no-op).
    """
    line = f"  - {resource_line}\n"
    if resource_line in current:
        return current
    marker = "patches:\n"
    if marker in current:
        return current.replace(marker, line + marker)
    return current.rstrip("\n") + "\n" + line


def _env_name(slug: str, secret_key: str) -> str:
    """Deterministic env var name for one capability secret key.

    ``MAKEWAY_<SLUG>_<KEY>`` — the slug keeps multiple capabilities distinct
    (``storage`` vs ``db`` vs a queue named ``order-events``), and the
    camelCase/snake key is uppercased-snake so it is safe in POSIX/env
    namespaces (``queueUrl`` -> ``QUEUE_URL``, ``bucketName`` -> ``BUCKET_NAME``,
    ``aws_access_key_id`` -> ``AWS_ACCESS_KEY_ID``).
    """
    slug_part = re.sub(r"[^A-Za-z0-9]+", "_", slug).strip("_").upper()
    key_part = re.sub(r"(?<!^)(?=[A-Z])", "_", secret_key).upper()
    key_part = re.sub(r"[^A-Za-z0-9]+", "_", key_part).strip("_")
    return f"MAKEWAY_{slug_part}_{key_part}"


def _inject_env_patch(slug: str, services: list[str], secret_keys: list[str]) -> str:
    """Strategic-merge patch doc(s) that inject one capability Secret into the
    accessTo services.

    Each service Deployment gets ``env`` entries of the form
    ``{name: MAKEWAY_<SLUG>_<KEY>, valueFrom.secretKeyRef: {name: <slug>, key}
    }`` — the Secret is the ESO-materialized one (ExternalSecret target name =
    claim slug) living in the same ``{app}-{env}`` namespace.
    """
    docs = []
    for svc in services:
        env_yaml = "\n".join(
            f"            - name: {_env_name(slug, key)}\n"
            f"              valueFrom:\n"
            f"                secretKeyRef:\n"
            f"                  name: {slug}\n"
            f"                  key: {key}"
            for key in secret_keys
        )
        docs.append(
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            f"  name: {svc}\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            f"        - name: {svc}\n"
            f"          env:\n{env_yaml}"
        )
    return "\n---\n".join(docs) + "\n"


def _add_kustomization_patch(current: str, patch_line: str) -> str:
    """Insert ``  - path: <patch_line>`` into an env kustomization's patches list.

    The generated kustomization lists ``patches:`` with one ``- path:`` entry
    per service. New injection patches (``inject/<slug>-env.yaml``) are inserted
    as the first entry (idempotent — a repeated line is a no-op).
    """
    line = f"  - path: {patch_line}\n"
    if patch_line in current:
        return current
    marker = "patches:\n"
    if marker in current:
        return current.replace(marker, marker + line)
    return current.rstrip("\n") + "\n" + line


def _gitops_inject_envs(
    app_name: str, env: str, claim: dict, access_to: list, secret_value: dict
) -> None:
    """Commit the env-injection patch + kustomize entry for one claim.

    For every service the capability grants access to (``accessTo``), add a
    strategic-merge patch that injects the capability's ESO-materialized Secret
    keys into the service Deployment as ``MAKEWAY_<slug>_<KEY>`` env vars. Runs
    during extract, after the ExternalSecret for the claim is committed.
    """
    services = sorted(
        {
            s.rsplit(f"-{env}", 1)[0] if s.endswith(f"-{env}") else s
            for s in (access_to or [])
        }
    )
    if not services:
        return

    slug = claim["slug"]
    env_dir = f"argocd/apps/{app_name}/envs/{env}"
    patch_path = f"{env_dir}/inject/{slug}-env.yaml"
    patch = _inject_env_patch(slug, services, secret_value.keys())

    files = {patch_path: patch}
    kustomization_path = f"{env_dir}/kustomization.yaml"
    current = _git_get_file(PLATFORM_REPO, kustomization_path) or ""
    updated = _add_kustomization_patch(current, f"inject/{slug}-env.yaml")
    if updated != current:
        files[kustomization_path] = updated

    _git_upsert_files(
        PLATFORM_REPO,
        files,
        f"makeway: inject {slug} env into {env} services",
    )


def _gitops_external_secret(
    app_name: str, env: str, claim: dict, sm_name: str
) -> None:
    """Commit the ExternalSecret + env-overlay resource entry to gitops."""
    with open(
        os.path.join(TEMPLATES_DIR, "external-secret.yaml"), "r", encoding="utf-8"
    ) as handle:
        template = handle.read()

    env_dir = f"argocd/apps/{app_name}/envs/{env}"
    es_path = f"{env_dir}/external-secrets/{claim['slug']}-external-secret.yaml"
    es_content = _render(
        template,
        TARGET_NAME=claim["slug"],
        NAMESPACE=claim["namespace"],
        SM_SECRET_NAME=sm_name,
    )

    files = {es_path: es_content}

    kustomization_path = f"{env_dir}/kustomization.yaml"
    current = _git_get_file(PLATFORM_REPO, kustomization_path) or ""
    updated = _add_kustomization_resource(
        current, f"external-secrets/{claim['slug']}-external-secret.yaml"
    )
    if updated != current:
        files[kustomization_path] = updated

    _git_upsert_files(
        PLATFORM_REPO,
        files,
        f"makeway: external-secret for {claim['slug']} ({env})",
    )


def _extract(request_id: int, job_id: int, execution_arn: str | None, event: dict) -> dict:
    details = _control_plane("GET", f"/internal/requests/{request_id}")
    app_name = details["app"]["appName"]
    account_id = _account_id()

    # Teardown runs do no credential work: an env delete already dropped the
    # whole env overlay (Step-1) and swept its SM/IAM artifacts (apply); an
    # update's removals had their gitops entries stripped and their per-claim
    # credentials deleted in apply. The control plane purges the rows on
    # SUCCESS — reporting success here is what triggers that purge.
    if details.get("requestType") == REQUEST_TYPE_DELETE:
        _report(request_id, job_id, "success", execution_arn)
        return {
            "status": "success",
            "request_id": request_id,
            "job_id": job_id,
            "capabilities": [],
        }

    removed = _removed_capability_keys(details)

    reports = []
    failures = []

    for cap in details.get("capabilities") or []:
        if _capability_is_removed(cap, removed):
            # Teardown target — nothing to mirror, nothing to commit.
            continue
        cap_id = cap["capabilityId"]
        cap_type = cap["capabilityType"]
        env = cap.get("environment") or "qa"
        claims = _claims_for(app_name, cap, account_id)

        if not claims:
            # Unknown capability type — nothing to provision yet.
            reports.append(
                {
                    "capabilityId": cap_id,
                    "status": "success",
                    "outputRef": {
                        "provisioned": False,
                        "reason": f"no crossplane composition for {cap_type}",
                    },
                }
            )
            continue

        try:
            outputs = []
            sm_arns = {}
            for claim in claims:
                conn = _read_connection_secret(claim)
                identity = {}
                if claim["aws_api"] and cap_type in AWS_API_CAPABILITIES:
                    identity = _ensure_aws_identity(app_name, env, claim, conn)

                secret_value = {**conn, **identity}
                sm_arn = _sm_merge_secret(claim["sm_name"], secret_value)
                sm_arns[claim["slug"]] = sm_arn

                _gitops_external_secret(app_name, env, claim, claim["sm_name"])

                # Inject the capability's secret into the services granted
                # access (accessTo) as MAKEWAY_<slug>_<KEY> env vars, via an
                # env overlay strategic-merge patch.
                access_to = cap.get("accessToServices") or []
                _gitops_inject_envs(app_name, env, claim, access_to, secret_value)

                outputs.append(
                    {
                        "slug": claim["slug"],
                        "connection": conn,
                        "secretsManagerArn": sm_arn,
                    }
                )

            # First claim's ARN is the capability's headline secretRef; all ARNs
            # are listed under outputRef so the platform can find them.
            secret_ref = sm_arns[claims[0]["slug"]] if sm_arns else None
            reports.append(
                {
                    "capabilityId": cap_id,
                    "status": "success",
                    "outputRef": {
                        "provisioned": True,
                        "claims": [
                            {
                                "slug": out["slug"],
                                "connection": out["connection"],
                                "secretsManagerArn": out["secretsManagerArn"],
                            }
                            for out in outputs
                        ],
                    },
                    "secretRef": secret_ref,
                }
            )
        except Exception as exc:  # noqa: BLE001 — partial failure, keep going
            logger.exception(
                "extract failed for capability %s (request_id=%s)", cap_id, request_id
            )
            failures.append(cap_id)
            reports.append(
                {
                    "capabilityId": cap_id,
                    "status": "failed",
                    "errorMessage": str(exc)[:2000],
                }
            )

    if failures:
        _report(
            request_id,
            job_id,
            "failed",
            execution_arn,
            error=f"capabilities failed: {', '.join(map(str, failures))}",
            capabilities=reports,
        )
        raise RuntimeError(f"extract failed for capabilities {failures}")
    else:
        _report(request_id, job_id, "success", execution_arn, capabilities=reports)

    return {
        "status": "success",
        "request_id": request_id,
        "job_id": job_id,
        "capabilities": reports,
    }


# --------------------------------------------------------------------------- #
# Handler — dispatch on action
# --------------------------------------------------------------------------- #

ACTIONS = {"apply": _apply, "check": _check, "extract": _extract}


def handler(event, context):
    action = event.get("action")
    request_id = int(event["request_id"])
    job_id = int(event.get("job_id", 0))
    execution_arn = event.get("execution_arn")

    logger.info(
        "Step 2 (%s) starting request_id=%s job_id=%s execution=%s",
        action,
        request_id,
        job_id,
        execution_arn,
    )

    fn = ACTIONS.get(action)
    if fn is None:
        raise RuntimeError(f"unknown Step-2 action '{action}'")

    try:
        return fn(request_id, job_id, execution_arn, event)
    except Exception as exc:  # noqa: BLE001 — report failure for SFN retry
        logger.exception("Step 2 %s failed request_id=%s", action, request_id)
        if action != "check":
            try:
                _report(request_id, job_id, "failed", execution_arn, error=str(exc)[:2000])
            except Exception as report_error:  # noqa: BLE001
                logger.warning("failed to report failure to control plane: %s", report_error)
        raise
