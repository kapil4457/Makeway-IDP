"""Pure-logic smoke test for the Step-1 handler (no network, no AWS).

Covers the state-machine contract: every handler() return path must carry the
keys the SFN payload templates reference — "Step2 Apply" reads $.request_id /
$.job_id from Step-1's output, and each Task's output replaces the next state's
entire input (no ResultPath), so a bare skip dict would fail the execution.
Run:  python _smoke_step1.py
"""
import importlib.util
import os
import sys
from pathlib import Path

# The handler reads its configuration at import time — supply dummy values so
# the module is importable without a live environment (no secret/network call
# happens at import).
os.environ.setdefault("GITHUB_OWNER", "kapil4457")
os.environ.setdefault("GITHUB_TOKEN_SECRET_ID", "makeway/test-github-pat")
os.environ.setdefault("CONTROL_PLANE_URL", "http://localhost:8000")
os.environ.setdefault("INTERNAL_API_KEY", "test-key")

H = Path(__file__).resolve().parent / "handler.py"
spec = importlib.util.spec_from_file_location("step1", H)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# 1. Skip path — job already success. Stub the control-plane call so the
#    handler exits early without touching GitHub or Secrets Manager.
m._control_plane = lambda method, path, payload=None: {"job": {"status": "success"}}
skip = m.handler({"request_id": 1, "job_id": 1, "execution_arn": "arn:test"}, None)
check(
    "skip keys {status, reason, request_id, job_id}",
    set(skip) == {"status", "reason", "request_id", "job_id"},
    str(skip),
)
check("skip request_id passthrough", skip.get("request_id") == 1)
check("skip job_id passthrough", skip.get("job_id") == 1)
check("skip status/reason", skip.get("status") == "skipped" and skip.get("reason") == "already_success")

# 2. job_id is optional on the wire (defaults to 0) but must still be in the
#    skip return — the SFN payload always references it.
skip = m.handler({"request_id": 2}, None)
check("skip default job_id", skip.get("job_id") == 0, str(skip))

# 3. _preserve_gitops_extras — re-renders of an env kustomization must carry
#    over the entries Step-2 extract committed (inject patches under patches,
#    external-secrets resources under resources), so retries and app updates
#    don't produce a PR that removes capability secret injection.
rendered = (
    "apiVersion: kustomize.config.k8s.io/v1beta1\n"
    "kind: Kustomization\n"
    "namespace: order-service-qa\n"
    "resources:\n"
    "  - namespace.yaml\n"
    "  - ../../base\n"
    "  - ../../apps/orders-api\n"
    "patches:\n"
    "  - path: orders-api-patch.yaml\n"
)
current = (
    "apiVersion: kustomize.config.k8s.io/v1beta1\n"
    "kind: Kustomization\n"
    "namespace: order-service-qa\n"
    "resources:\n"
    "  - namespace.yaml\n"
    "  - ../../base\n"
    "  - ../../apps/orders-api\n"
    "  - external-secrets/orders-external-secret.yaml\n"
    "patches:\n"
    "  - path: inject/orders-env.yaml\n"
    "  - path: orders-api-patch.yaml\n"
)
merged = m._preserve_gitops_extras(rendered, current)
check(
    "preserve inject patch line under patches",
    "  - path: inject/orders-env.yaml" in merged
    and merged.index("  - path: inject/orders-env.yaml") > merged.index("patches:"),
)
check(
    "preserve external-secrets resource line under resources",
    "  - external-secrets/orders-external-secret.yaml" in merged
    and merged.index("  - external-secrets/orders-external-secret.yaml") < merged.index("patches:"),
)
check(
    "preserve keeps rendered base intact",
    "  - ../../apps/orders-api" in merged and "  - path: orders-api-patch.yaml" in merged,
)
check(
    "preserve idempotent when line already present",
    m._preserve_gitops_extras(merged, current) == merged,
    m._preserve_gitops_extras(merged, current),
)
check(
    "preserve no-op on first creation (no current file)",
    m._preserve_gitops_extras(rendered, None) == rendered,
)
check(
    "preserve no-op when current has no extras",
    m._preserve_gitops_extras(rendered, rendered) == rendered,
)

# 4. _slug — DNS-safe, mirrors Step-2's claim-name derivation.
check("slug lowercases and dashes", m._slug("My DB") == "my-db")
check("slug strips punctuation", m._slug("Orders DB!!") == "orders-db")
check("slug empty falls back to default", m._slug("   ") == "default")

# 5. _blob_sha — must equal the sha git itself stores for the content
#    (`echo "hello" | git hash-object --stdin` -> ce0136...464a).
check(
    "blob sha matches git's object hash",
    m._blob_sha("hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a",
)
check(
    "blob sha distinguishes content",
    m._blob_sha("hello\n") != m._blob_sha("hello \n"),
)

# 6. _deletion_tree_entries — git-database delete entries (sha: null).
entries = m._deletion_tree_entries(["a/b.yaml", "a/c.yaml"])
check(
    "deletion entries carry sha null + blob type",
    entries == [
        {"path": "a/b.yaml", "mode": "100644", "type": "blob", "sha": None},
        {"path": "a/c.yaml", "mode": "100644", "type": "blob", "sha": None},
    ],
    str(entries),
)

# 7. _paths_under_prefix — directory prefixes expand; exact files match
#    themselves; unrelated paths stay out.
paths = [
    "argocd/apps/orders/envs/qa/kustomization.yaml",
    "argocd/apps/orders/envs/qa/inject/db-env.yaml",
    "argocd/apps/orders/envs/uat/kustomization.yaml",
    "argocd/apps/orders/base/namespaces.yaml",
    ".github/workflows/ci-orders-api.yaml",
]
check(
    "prefix expansion collects the whole env overlay",
    m._paths_under_prefix(paths, ["argocd/apps/orders/envs/qa/"]) == [
        "argocd/apps/orders/envs/qa/kustomization.yaml",
        "argocd/apps/orders/envs/qa/inject/db-env.yaml",
    ],
)
check(
    "exact path counts as its own prefix",
    m._paths_under_prefix(paths, [".github/workflows/ci-orders-api.yaml"]) == [
        ".github/workflows/ci-orders-api.yaml",
    ],
)
check(
    "multiple prefixes union",
    m._paths_under_prefix(paths, ["argocd/apps/orders/envs/uat/", ".github/"]) == [
        "argocd/apps/orders/envs/uat/kustomization.yaml",
        ".github/workflows/ci-orders-api.yaml",
    ],
)
check("no matches -> empty", m._paths_under_prefix(paths, ["nomatch/"]) == [])

# 8. _preserve_gitops_extras exclude_slugs — a removed capability's extract
#    lines are NOT carried over (its files are deleted in the same push),
#    while surviving capabilities' lines still are.
current_with_two = (
    "kind: Kustomization\n"
    "resources:\n"
    "  - ../../base\n"
    "  - external-secrets/orders-db-external-secret.yaml\n"
    "  - external-secrets/payments-external-secret.yaml\n"
    "patches:\n"
    "  - path: inject/orders-db-env.yaml\n"
    "  - path: inject/payments-env.yaml\n"
)
rendered_plain = "kind: Kustomization\nresources:\n  - ../../base\npatches:\n"
merged_excl = m._preserve_gitops_extras(rendered_plain, current_with_two, {"orders-db"})
check(
    "excluded slug's inject + external-secrets lines dropped",
    "orders-db" not in merged_excl,
    merged_excl,
)
check(
    "surviving slug's lines still carried",
    "external-secrets/payments-external-secret.yaml" in merged_excl
    and "path: inject/payments-env.yaml" in merged_excl,
    merged_excl,
)

# 9. _capability_slugs — mirrors Step-2 _claims_for so removals target the
#    exact file names extract committed.
check(
    "slugs: rel_database uses config name",
    m._capability_slugs({"type": "rel_database", "name": "My DB"}) == ["my-db"],
)
check(
    "slugs: rel_database without name falls back",
    m._capability_slugs({"type": "rel_database"}) == ["db"],
)
check("slugs: storage is fixed", m._capability_slugs({"type": "storage"}) == ["storage"])
check(
    "slugs: messaging per queue + notification",
    m._capability_slugs({
        "type": "messaging",
        "queue": [{"name": "Order Events"}],
        "notification": {"type": "email"},
    }) == ["order-events", "notification"],
)
check("slugs: unknown type -> empty", m._capability_slugs({"type": "whatever"}) == [])

# 10. _removed_slugs_by_env — only the named env's capabilities of the named
#     types produce slugs; same capability type in another env survives.
caps = [
    {"capabilityType": "rel_database", "environment": "qa",
     "config": {"type": "rel_database", "name": "Orders DB"}},
    {"capabilityType": "rel_database", "environment": "uat",
     "config": {"type": "rel_database", "name": "Orders DB"}},
    {"capabilityType": "storage", "environment": "qa", "config": {"type": "storage"}},
    {"capabilityType": "messaging", "environment": "qa",
     "config": {"type": "messaging", "queue": [{"name": "Order Events"}],
                "notification": {"type": "email"}}},
]
slugs = m._removed_slugs_by_env(
    caps,
    [{"env": "qa", "remove_capabilities": ["rel_database", "messaging"]}],
)
check(
    "removed slugs scoped to the target env",
    slugs == {"qa": {"orders-db", "order-events", "notification"}},
    str(slugs),
)
check(
    "no removals -> empty map",
    m._removed_slugs_by_env(caps, [{"env": "qa", "services": ["orders-api"]}]) == {},
)
check(
    "storage removal yields its fixed slug",
    m._removed_slugs_by_env(caps, [{"env": "qa", "remove_capabilities": ["storage"]}])
    == {"qa": {"storage"}},
)

# 11. _fully_removed_bases — a base removed from every env it exists in loses
#     its shared gitops folder + CI workflow; a partial removal keeps them.
services = [
    {"svcName": "orders-api-qa"},
    {"svcName": "orders-api-uat"},
    {"svcName": "payments-qa"},
    {"svcName": "billing-qa"},
    {"svcName": "billing-uat"},
]
envs = ["qa", "uat", "prod"]
fully = m._fully_removed_bases(
    services,
    envs,
    [
        {"env": "qa", "remove_services": ["orders-api", "payments"]},
        {"env": "uat", "remove_services": ["orders-api"]},
    ],
)
check(
    "base removed from all its envs is fully removed",
    "orders-api" in fully and "payments" in fully,
    str(fully),
)
check(
    "base kept in one env is not fully removed",
    "billing" not in fully,
    str(fully),
)
check(
    "no removal lists -> empty",
    m._fully_removed_bases(services, envs, [{"env": "qa"}]) == set(),
)
check(
    "removal of unknown base is inert",
    m._fully_removed_bases(services, envs, [{"env": "qa", "remove_services": ["ghost"]}])
    == set(),
)

print()
if fails:
    sys.exit("FAILED: " + ", ".join(fails))
print("step1 handler smoke: ALL PASS")