"""Pure-logic smoke test for the ArgoCD health reporter (no network, no AWS).

Covers the Application -> deployment-setup report mapping end to end:
status/health/sync/operationState translation, per-service batch expansion,
error carrying + clearing, label parsing, sweep-target resolution (registry
rows vs the Lambda-env fallback), and the 'skip unlabeled' branch in the
sweep loop.

Run:  python _smoke_health_reporter.py
"""
import importlib.util
import os
from pathlib import Path

# The handler reads its configuration at import time — supply dummy values so
# the pure functions are testable without a live environment.
os.environ.setdefault("CONTROL_PLANE_URL", "http://localhost:8000")
os.environ.setdefault("INTERNAL_API_KEY", "test-key")
os.environ.setdefault("KUBE_API_ENDPOINT", "https://127.0.0.1:6443")
os.environ.setdefault("KUBE_TOKEN", "test-token")

H = Path(__file__).resolve().parent / "handler.py"
spec = importlib.util.spec_from_file_location("health_reporter", H)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def app(name, labels=None, status=None):
    return {
        "metadata": {
            "name": name,
            "labels": labels or {"app": "order-service", "environment": "qa", "managed-by": "makeway"},
        },
        "spec": {},
        "status": status or {},
    }


# --- Status mapping ----------------------------------------------------------

# Healthy.
r = m._report_for(app("order-service-qa", status={"health": {"status": "Healthy"}, "sync": {"status": "Synced"}}))
check("Healthy -> success", r["status"] == "success", r["status"])
check("Healthy -> no error", r["errorMessage"] is None)

# Degraded / Missing -> failed, with operationState message.
for h in ("Degraded", "Missing"):
    r = m._report_for(
        app(
            "order-service-qa",
            status={
                "health": {"status": h},
                "sync": {"status": "Synced"},
                "operationState": {"phase": "Failed", "message": "rds down"},
            },
        )
    )
    check(f"{h} -> failed", r["status"] == "failed", r["status"])
    if h == "Degraded":
        check("Degraded carries op error", r["errorMessage"] == "rds down", r["errorMessage"])

# Suspended.
r = m._report_for(app("order-service-qa", status={"health": {"status": "Suspended"}}))
check("Suspended -> suspended", r["status"] == "suspended", r["status"])

# op phase Failed (no health) -> failed.
r = m._report_for(app("order-service-qa", status={"operationState": {"phase": "Failed", "message": "sync timeout"}}))
check("opFailed -> failed", r["status"] == "failed", r["status"])
check("opFailed error", r["errorMessage"] == "sync timeout", r["errorMessage"])

# Progressing (mid-sync).
r = m._report_for(app("order-service-qa", status={"operationState": {"phase": "Running"}}))
check("Running -> progressing", r["status"] == "progressing", r["status"])

# Synced but health empty.
r = m._report_for(app("order-service-qa", status={"sync": {"status": "Synced"}}))
check("Synced-no-health -> synced", r["status"] == "synced", r["status"])

# Never synced.
r = m._report_for(app("order-service-qa", status={}))
check("empty status -> unknown", r["status"] == "unknown", r["status"])

# lastSyncedAt flows from operationState.finishedAt.
r = m._report_for(
    app(
        "order-service-qa",
        status={"health": {"status": "Healthy"}, "operationState": {"finishedAt": "2026-08-30T12:00:00Z"}},
    )
)
check("lastSyncedAt carried", r["lastSyncedAt"] == "2026-08-30T12:00:00Z", r["lastSyncedAt"])

# --- Batch expansion -----------------------------------------------------------

# Healthy App -> one success report per service, no error on any.
batch = m._report_batch(
    app("order-service-qa", status={"health": {"status": "Healthy"}}),
    [11, 12],
)
check("healthy batch count", len(batch) == 2, len(batch))
check("healthy batch statuses", all(b["status"] == "success" for b in batch))
check("healthy batch no errors", all("errorMessage" not in b for b in batch))
check("healthy batch app name", batch[0]["argocdAppName"] == "order-service-qa")

# Failed App -> every report carries the error; fallback when op has no message.
batch = m._report_batch(
    app("order-service-qa", status={"health": {"status": "Degraded"}}),
    [11],
)
check("failed batch error set", "errorMessage" in batch[0], batch[0])
check("failed batch fallback msg", batch[0]["errorMessage"] == "ArgoCD Application order-service-qa is not healthy", batch[0]["errorMessage"])

# --- Label parsing + sweep skip ------------------------------------------------

check("labels parsed", m._app_labels(app("x")) == ("order-service", "qa"), m._app_labels(app("x")))
check(
    "unlabeled -> None pair",
    m._app_labels(app("x", labels={"managed-by": "makeway"})) == (None, None),
    m._app_labels(app("x", labels={"managed-by": "makeway"})),
)

# --- Sweep targets ---------------------------------------------------------------

# Empty registry -> single fallback target riding the Lambda env KUBE_*.
fallback = m._sweep_targets([])
check("empty registry -> fallback", len(fallback) == 1, fallback)
check("fallback rides env vars", fallback[0] == {
    "clusterName": "fallback", "environment": None,
    "endpoint": None, "token": None, "caCert": None,
}, fallback)

# Registry rows become per-cluster targets; None creds pass through as None
# (the reporter falls back to its Lambda env per field).
targets = m._sweep_targets(
    [
        {
            "clusterId": 1,
            "clusterName": "qa-cluster",
            "environment": "qa",
            "kubeApiEndpoint": "https://k8s.qa",
            "kubeToken": "qa-token",
            "kubeCaCert": "qa-ca",
        },
        {
            "clusterId": 2,
            "clusterName": "uat-cluster",
            "environment": "uat",
            "kubeApiEndpoint": "https://k8s.uat",
            "kubeToken": None,
            "kubeCaCert": None,
        },
    ]
)
check("registry -> 2 targets", len(targets) == 2, targets)
check(
    "qa target carries creds",
    (targets[0]["endpoint"], targets[0]["token"], targets[0]["caCert"])
    == ("https://k8s.qa", "qa-token", "qa-ca"),
    targets[0],
)
check(
    "tokenless cluster -> None creds",
    (targets[1]["endpoint"], targets[1]["token"], targets[1]["caCert"])
    == ("https://k8s.uat", None, None),
    targets[1],
)


def _fake_control_plane(method, path, payload=None):
    raise AssertionError(f"unexpected control-plane call {method} {path}")


# Unlabeled App in the sweep is skipped without calling the control plane.
# Empty registry -> fallback cluster (fetch stubbed to []).
apps = [
    app("stale", labels={"managed-by": "makeway"}),
]
m._fetch_clusters = lambda: []
m._list_managed_applications = lambda **_: apps
m._control_plane = _fake_control_plane
res = m.handler({}, None)
check("unlabeled skipped", res["skipped"] == 1, res)
check("unlabeled not reported", res["reported"] == 0, res)
check("fallback sweep counted 1 cluster", res["clusters"] == 1, res)

# --- Multi-cluster sweep -----------------------------------------------------------

# Two registry clusters; only the qa one answers the list call. The labeled
# app reports through the deployment group; the token-less uat row exercises
# the per-field Lambda-env fallback (list succeeds, no Applications).
CLUSTERS = [
    {
        "clusterId": 1,
        "clusterName": "qa-cluster",
        "environment": "qa",
        "kubeApiEndpoint": "https://k8s.qa",
        "kubeToken": "qa-token",
        "kubeCaCert": None,
    },
    {
        "clusterId": 2,
        "clusterName": "uat-cluster",
        "environment": "uat",
        "kubeApiEndpoint": "https://k8s.uat",
        "kubeToken": None,
        "kubeCaCert": None,
    },
]
seen_endpoints = []


def fake_cp_multi(method, path, payload=None):
    if path == "/internal/clusters":
        return {"clusters": CLUSTERS}
    if path == "/internal/deployment-groups/order-service/qa":
        return {"env": "qa", "svcIds": [11]}
    if method == "POST" and path == "/internal/deployment-setup":
        return {"message": "ok"}
    raise AssertionError(f"unexpected control-plane call {method} {path}")


def fake_list_multi(*, endpoint=None, token=None, ca_cert=None):
    seen_endpoints.append(endpoint)
    if endpoint == "https://k8s.qa":
        return [
            app(
                "order-service-qa",
                status={"health": {"status": "Healthy"}, "sync": {"status": "Synced"}},
            )
        ]
    return []


posted = []


def fake_cp_capture(method, path, payload=None):
    if path == "/internal/clusters":
        return {"clusters": CLUSTERS}
    if path == "/internal/deployment-groups/order-service/qa":
        return {"env": "qa", "svcIds": [11]}
    if method == "POST" and path == "/internal/deployment-setup":
        posted.append(payload)
        return {"message": "ok"}
    raise AssertionError(f"unexpected control-plane call {method} {path}")


m._fetch_clusters = lambda: CLUSTERS
m._list_managed_applications = fake_list_multi
m._control_plane = fake_cp_multi
res = m.handler({}, None)
check("multi sweep visits both clusters", sorted(seen_endpoints) == ["https://k8s.qa", "https://k8s.uat"], seen_endpoints)
check("multi sweep reports 1", res["reported"] == 1, res)
check("multi sweep applications counted", res["applications"] == 1, res)
check("multi sweep cluster count", res["clusters"] == 2, res)

# Dead cluster: a failing list call must not block the other clusters.
def fake_list_broken(*, endpoint=None, token=None, ca_cert=None):
    if endpoint == "https://k8s.qa":
        raise RuntimeError("kube list Applications -> HTTP 401")
    return []


m._list_managed_applications = fake_list_broken
res = m.handler({}, None)
check("dead cluster counted failed", res["failed"] == 1, res)
check("healthy cluster still swept", res["applications"] == 0 and res["reported"] == 0, res)

# End-to-end reporting through the multi-cluster loop (capture POST bodies).
posted.clear()
m._list_managed_applications = fake_list_multi
m._control_plane = fake_cp_capture
res = m.handler({}, None)
check("e2e reported 1 svc", res["reported"] == 1 and len(posted) == 1, res)
check("e2e payload shape", posted[0]["svcId"] == 11 and posted[0]["status"] == "success", posted)

if fails:
    print(f"\n{len(fails)} smoke failure(s): {fails}")
    raise SystemExit(1)
print("\nAll health-reporter smoke checks passed.")