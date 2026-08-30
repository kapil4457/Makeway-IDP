"""Pure-logic smoke test for the ArgoCD health reporter (no network, no AWS).

Covers the Application -> deployment-setup report mapping end to end:
status/health/sync/operationState translation, per-service batch expansion,
error carrying + clearing, label parsing, and the 'skip unlabeled' branch in
the sweep loop.

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


def _fake_control_plane(method, path, payload=None):
    raise AssertionError(f"unexpected control-plane call {method} {path}")


# Unlabeled App in the sweep is skipped without calling the control plane.
apps = [
    app("stale", labels={"managed-by": "makeway"}),
]
m._list_managed_applications = lambda: apps
m._control_plane = _fake_control_plane
res = m.handler({}, None)
check("unlabeled skipped", res["skipped"] == 1, res)
check("unlabeled not reported", res["reported"] == 0, res)

if fails:
    print(f"\n{len(fails)} smoke failure(s): {fails}")
    raise SystemExit(1)
print("\nAll health-reporter smoke checks passed.")