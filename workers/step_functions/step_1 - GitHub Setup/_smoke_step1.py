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

# 12. Regression: the PAT getter must return the secret's token STRING — this
#     smoke used to pass while production 401'd, because it never exercised the
#     auth plumbing (the skip-path tests stub the control plane and return
#     before any GitHub call). The getter was once named `_github_token`, the
#     same name as the module-level cache variable, which clobbered it: the
#     lazy `is None` check always saw the function object itself, Secrets
#     Manager was never read, and every GitHub call sent
#     `Bearer <function object>` -> 401 Bad credentials. These checks fail for
#     both that state (function returned / AttributeError) and a None cache.
_fake_secret_calls = []


def _fake_get_secret_value(SecretId):
    _fake_secret_calls.append(SecretId)
    # Padded on purpose: the getter must strip the value (copy/paste PATs often
    # carry trailing whitespace, and GitHub rejects it).
    return {"SecretString": "  test-token-123  "}


_saved_secrets_client = m._secrets_client
_saved_github_token = m._github_token
_saved_http = m._http
try:
    m._secrets_client = type(
        "FakeSecretsClient", (), {"get_secret_value": staticmethod(_fake_get_secret_value)}
    )()
    m._github_token = None  # cold cache — force the lazy secret read

    token = m._get_github_token()
    check(
        "PAT getter returns the token string, not a function object/None",
        isinstance(token, str) and token == "test-token-123",
        repr(token),
    )
    check(
        "PAT getter strips the secret value",
        token == "test-token-123",
        repr(token),
    )
    check(
        "PAT getter reads the configured secret id",
        _fake_secret_calls == [m.GITHUB_TOKEN_SECRET_ID],
        str(_fake_secret_calls),
    )
    m._get_github_token()
    check(
        "PAT is cached within the execution (one secret read)",
        len(_fake_secret_calls) == 1,
        str(_fake_secret_calls),
    )

    # The failure mode was only visible in the Authorization header — verify it
    # end-to-end through _gh_status with a recording _http stub.
    seen_headers = {}
    m._http = lambda method, url, payload=None, headers=None, timeout=60: (
        seen_headers.update(headers or {}) or (200, {})
    )
    m._gh_status("GET", "/rate_limit")
    check(
        "Authorization header carries the token string",
        seen_headers.get("Authorization") == "Bearer test-token-123",
        repr(seen_headers.get("Authorization")),
    )
finally:
    m._secrets_client = _saved_secrets_client
    m._github_token = _saved_github_token
    m._http = _saved_http

# 13. _ensure_repo — the create call must match the owner's account kind.
#     Regression: it unconditionally POSTed /orgs/<owner>/repos, which is a
#     hard 404 ("Not Found") when GITHUB_OWNER is a personal account like
#     kapil4457 — that endpoint only exists for real organizations.
saved_gh, saved_gh_status = m._gh, m._gh_status
try:

    def _install_gh(repo_status, owner_type=None, token_login=None, repo="orders-app"):
        """Stub the GitHub layer. Returns the list of _gh() POST paths."""
        posts = []

        def fake_gh(method, path, payload=None, params=None):
            posts.append(path)
            return {"full_name": f"{m.GITHUB_OWNER}/{repo}", "name": repo}

        def fake_gh_status(method, path, payload=None):
            if method == "GET" and path == f"/repos/{m.GITHUB_OWNER}/{repo}":
                return repo_status, {"name": repo}
            if owner_type is not None and method == "GET" and path == f"/users/{m.GITHUB_OWNER}":
                return 200, {"login": m.GITHUB_OWNER, "type": owner_type}
            if token_login is not None and method == "GET" and path == "/user":
                return 200, {"login": token_login, "id": 1}
            return 500, {"message": "unexpected path in test stub"}

        m._gh, m._gh_status = fake_gh, fake_gh_status
        return posts

    posts = _install_gh(200)
    m._ensure_repo("orders-app")
    check("existing repo is reused without a create POST", posts == [], str(posts))

    posts = _install_gh(404, owner_type="User", token_login=m.GITHUB_OWNER)
    m._ensure_repo("orders-app")
    check(
        "personal-account owner creates via POST /user/repos",
        posts == ["/user/repos"],
        str(posts),
    )

    posts = _install_gh(404, owner_type="Organization", token_login="some-bot")
    m._ensure_repo("orders-app")
    check(
        "organization owner creates via POST /orgs/<owner>/repos",
        posts == [f"/orgs/{m.GITHUB_OWNER}/repos"],
        str(posts),
    )

    posts = _install_gh(404, owner_type="User", token_login="someone-else")
    try:
        m._ensure_repo("orders-app")
        check("PAT/owner mismatch raises", False, "no exception raised")
    except RuntimeError as exc:
        check(
            "PAT/owner mismatch raises a clear error and never POSTs",
            "not an organization" in str(exc) and posts == [],
            f"{exc} posts={posts}",
        )
    except Exception as exc:  # noqa: BLE001
        check("PAT/owner mismatch raises RuntimeError", False, repr(exc))

    posts = _install_gh(403)
    try:
        m._ensure_repo("orders-app")
        check("non-404 on existence GET raises", False, "no exception raised")
    except RuntimeError as exc:
        check(
            "non-404 on existence GET raises without a create POST",
            "HTTP 403" in str(exc) and posts == [],
            f"{exc} posts={posts}",
        )
    except Exception as exc:  # noqa: BLE001
        check("non-404 on existence GET raises RuntimeError", False, repr(exc))
finally:
    m._gh, m._gh_status = saved_gh, saved_gh_status

print()
if fails:
    sys.exit("FAILED: " + ", ".join(fails))
print("step1 handler smoke: ALL PASS")