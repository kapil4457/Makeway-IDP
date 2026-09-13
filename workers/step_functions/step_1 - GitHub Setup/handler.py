"""Step 1 — GitHub Setup worker for the Makeway app-creation state machine.

Consumed as a Lambda task by the app-creation state machine. For one app
creation request this step:

1. Marks the job/request IN_PROGRESS through the control-plane internal API.
2. Pulls the full request details (app, services, environments) from the
   control plane.
3. Creates the app's **services monorepo** (<appName>, public, branch ``main``)
   and scaffolds one golden-path folder per service (deduplicated by base name
   — the ``-<env>`` suffix is stripped so ``orders-api-qa`` and
   ``orders-api-uat`` share one ``orders-api`` folder).
4. Writes a per-service CI workflow (``.github/workflows/ci-<service>.yaml``)
   that runs on merge to the branch that promotes each tier
   (``feature/*`` → qa, ``release/*`` → uat, ``main`` → prod), builds the
   service image, and bumps that environment's image tag in the env overlays
   under ``argocd/apps/<appName>/``.
5. Publishes the app's **GitOps configuration into the Makeway platform repo
   itself** (no separate per-app gitops repo): ``argocd/apps/<appName>/`` with
   the base/apps/envs kustomize layout. Because the platform repo's ``main`` is
   the ArgoCD deploy branch, the content lands via a feature-branch PR that is
   auto-merged when possible and left open for review otherwise.
6. Reports SUCCESS/FAILED (repo URLs + per-service ``repoPath``) back to the
   control plane.

Teardown modes: the same pipeline reconciles deletions. A ``delete_app``
request strips the target environment's GitOps overlay (the whole
``argocd/apps/<appName>/`` tree when it is the app's last environment); an
``update_app`` request whose entries carry ``remove_services`` /
``remove_capabilities`` regenerates the overlays without those items and
deletes their files. The control plane purges the desired-state rows only once
the pipeline reports SUCCESS, so retries re-derive everything from live rows.

Idempotency: repo existence is checked first (``GET /repos/{owner}/{repo}``)
and the tree push diffs against the current git tree by blob content, so
re-running skips no-op commits and reuses the existing feature branch. If the
job already reached ``success``, the handler exits early.
"""

import base64
import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Environment (set on the Lambda) ---
GITHUB_OWNER = os.environ["GITHUB_OWNER"]
GITHUB_TOKEN_SECRET_ID = os.environ["GITHUB_TOKEN_SECRET_ID"]
CONTROL_PLANE_URL = os.environ["CONTROL_PLANE_URL"].rstrip("/")
INTERNAL_API_KEY = os.environ["INTERNAL_API_KEY"]
REGION = os.environ.get("AWS_REGION", "ap-south-1")

# Repository hosting the GitOps configs — this platform repo. Step 1 writes
# argocd/apps/<appName>/ here instead of creating a per-app gitops repository.
MAKEWAY_PLATFORM_REPO = os.environ.get("MAKEWAY_PLATFORM_REPO", "Makeway-IDP")
PLATFORM_REPO = f"{GITHUB_OWNER}/{MAKEWAY_PLATFORM_REPO}"

STEP = "create_project"

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
CI_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ci_templates")
GITOPS_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gitops_templates")

# Stack key -> template folder name (ServiceType.value is the stack key).
STACK_TEMPLATE_DIR = {
    "fast-api": "fast-api",
    "node-js": "node-js",
    "spring-boot": "spring-boot",
}

# Stack key -> runtime container port baked into the Deployment/Service.
STACK_PORT = {
    "fast-api": 8000,
    "node-js": 3000,
    "spring-boot": 8080,
}

# The image line starts as a placeholder so the overlay is valid before the
# first CI run; the env overlay always patches this value, and when the user
# sets the DOCKERHUB_IMAGE repository variable, CI rewrites the real tag.
PLACEHOLDER_IMAGE = "makeway-placeholder/__SERVICE_NAME__:pending-first-build"

# Environment tiers and the branch that promotes each one's image. A service's
# CI workflow maps the merged branch to its environment and bumps that env's
# image tag in the gitops (`argocd/apps/<appName>/envs/<env>/<service>-patch.yaml`):
#   feature/* -> qa, release/* -> uat, main -> prod.
# This is the canonical env set for every app — there is no dev environment.
ENV_BRANCH_MAP = {
    "feature": "qa",
    "release": "uat",
    "main": "prod",
}
GITOPS_ENVIRONMENTS = list(ENV_BRANCH_MAP.values())  # ["qa", "uat", "prod"]

# requestType values the control plane exposes on the request-details payload;
# the handler branches on them (create/update scaffold, delete tears down).
REQUEST_TYPE_DELETE = "delete_app"

# Commit author/committer is resolved at runtime from the PAT's own user
# (`GET /user`) so that "who authors the commit" and "who authenticates the
# push" are the same GitHub account — see `_git_identity()`.

_secrets_client = boto3.client("secretsmanager", region_name=REGION)
_github_token: str | None = None
_git_identity_cache: dict | None = None


# --------------------------------------------------------------------------- #
# Low-level HTTP helpers (stdlib only — the Lambda has no requests dependency)
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


def _github_token() -> str:
    global _github_token
    if _github_token is None:
        secret = _secrets_client.get_secret_value(SecretId=GITHUB_TOKEN_SECRET_ID)
        _github_token = secret["SecretString"].strip()
    return _github_token


def _git_identity() -> dict:
    """Commit author/committer for pushed commits, resolved from the PAT.

    The same token that authenticates the push also authors the commit, so the
    commits are clearly attributable to the token-owning account.
    """
    global _git_identity_cache
    if _git_identity_cache is None:
        user = _gh("GET", "/user")
        login = user["login"]
        _git_identity_cache = {
            "name": user.get("name") or login,
            # `<id>+<login>@users.noreply.github.com` is GitHub's guaranteed
            # noreply address for an account — no `user:email` scope needed.
            "email": f"{user['id']}+{login}@users.noreply.github.com",
        }
    return _git_identity_cache


def _gh(method: str, path: str, payload=None, params: dict | None = None):
    """GitHub REST call; raises on non-2xx."""
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


def _gh_status(method: str, path: str, payload=None):
    """GitHub REST call returning (status, body) without raising."""
    url = f"https://api.github.com{path}"
    return _http(
        method,
        url,
        payload,
        {
            "Authorization": f"Bearer {_github_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def _git_file(repo: str, path: str) -> str | None:
    """Read one file's current content from the repo's default branch.

    Returns None on 404 (file doesn't exist yet); raises on any other
    failure. Callers pass the bare repo name (``GITHUB_OWNER`` is prefixed
    here, matching the other git helpers). Used to carry entries earlier
    runs added to generated files — see ``_preserve_gitops_extras``.
    """
    status, body = _gh_status("GET", f"/repos/{GITHUB_OWNER}/{repo}/contents/{path}")
    if status == 404:
        return None
    if not 200 <= status < 300:
        detail = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)
        raise RuntimeError(f"github GET /contents/{path} -> HTTP {status}: {detail}")
    return base64.b64decode(body["content"]).decode("utf-8")


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
# Rendering & idempotent git-database pushes
# --------------------------------------------------------------------------- #

def _render(text: str, **tokens: str) -> str:
    for key, value in tokens.items():
        text = text.replace(f"__{key}__", value)
    return text


def _slug(value: str) -> str:
    """DNS-safe lower-case slug (``'My DB'`` -> ``'my-db'``) — mirrors Step-2."""
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "default"


def _collect_template_files(template_dir: str) -> dict[str, str]:
    """Walk a template dir and return {relative/path: content}."""
    files = {}
    for dirpath, _dirs, filenames in os.walk(template_dir):
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, template_dir).replace(os.sep, "/")
            with open(full_path, "r", encoding="utf-8") as handle:
                files[rel_path] = handle.read()
    return files


def _ensure_repo(repo: str):
    """Create ``repo`` under GITHUB_OWNER if it doesn't exist. Idempotent."""
    # Example : https://api.github.com/repos/kapil4457/makeway-idp
    status, body = _gh_status("GET", f"/repos/{GITHUB_OWNER}/{repo}")
    if status == 200:
        logger.info("repo %s already exists — reusing", repo)
        return
    if status == 404:
        created = _gh(
            "POST",
            f"/orgs/{GITHUB_OWNER}/repos",
            {
                "name": repo,
                "description": f"Makeway app '{repo}' (generated)",
                "private": False,
                "auto_init": True,
                "default_branch": "main",
                "has_issues": False,
                "has_projects": False,
                "has_wiki": False,
            },
        )
        logger.info("created repo %s", created["full_name"])
        return
    detail = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)
    raise RuntimeError(f"GET /repos/{GITHUB_OWNER}/{repo} -> HTTP {status}: {detail}")


def _blob_sha(content: str) -> str:
    """Git blob object sha for utf-8 content — the same hash GitHub stores."""
    data = content.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _deletion_tree_entries(paths: list[str]) -> list[dict]:
    """Git-database entries that delete ``paths`` (``sha: null`` removes the
    blob; a directory disappears with its last file)."""
    return [
        {"path": path, "mode": "100644", "type": "blob", "sha": None}
        for path in paths
    ]


def _paths_under_prefix(paths: list[str], prefixes: list[str]) -> list[str]:
    """Blob paths under any of ``prefixes`` (an exact path is its own prefix)."""
    return [
        path for path in paths
        if any(path.startswith(prefix) for prefix in prefixes)
    ]


def _push_tree(
    repo: str,
    files: dict[str, str],
    message: str,
    branch: str = "main",
    delete_paths: list[str] | tuple[str, ...] = (),
) -> bool:
    """Commit ``files`` ({path: content}) and delete ``delete_paths`` on
    ``branch`` via the git database API, in a single commit.

    The diff is by CONTENT: an existing path whose blob sha already matches the
    desired content is skipped, while a genuinely changed file — an env
    kustomization gaining or losing a service, say — is re-committed instead of
    silently dropped. ``delete_paths`` entries may be exact blob paths or
    directory prefixes; they are expanded against the current tree, so
    already-gone targets are naturally skipped. Returns whether a new commit
    was made.
    """
    ref = _gh("GET", f"/repos/{GITHUB_OWNER}/{repo}/git/refs/heads/{branch}")
    head_sha = ref["object"]["sha"]

    current_tree = _gh(
        "GET",
        f"/repos/{GITHUB_OWNER}/{repo}/git/trees/{head_sha}",
        params={"recursive": "1"},
    )
    current_blobs = {
        entry["path"]: entry["sha"]
        for entry in current_tree["tree"]
        if entry.get("type") == "blob"
    }

    # Create blobs (content-addressed — identical content returns the same sha).
    desired_blobs = {}
    for path, content in files.items():
        sha = _blob_sha(content)
        if current_blobs.get(path) == sha:
            continue
        blob = _gh(
            "POST",
            f"/repos/{GITHUB_OWNER}/{repo}/git/blobs",
            {"content": content, "encoding": "utf-8"},
        )
        desired_blobs[path] = blob["sha"]

    deletes = sorted(_paths_under_prefix(list(current_blobs), list(delete_paths)))

    if not desired_blobs and not deletes:
        logger.info("[%s/%s] no changes to push — already at desired tree", repo, branch)
        return False

    tree_entries = [
        {"path": path, "mode": "100644", "type": "blob", "sha": sha}
        for path, sha in desired_blobs.items()
    ] + _deletion_tree_entries(deletes)
    new_tree = _gh(
        "POST",
        f"/repos/{GITHUB_OWNER}/{repo}/git/trees",
        {"base_tree": current_tree["sha"], "tree": tree_entries},
    )
    identity = _git_identity()
    commit = _gh(
        "POST",
        f"/repos/{GITHUB_OWNER}/{repo}/git/commits",
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
        f"/repos/{GITHUB_OWNER}/{repo}/git/refs/heads/{branch}",
        {"sha": commit["sha"]},
    )
    logger.info(
        "[%s/%s] pushed %d files, deleted %d (%s)",
        repo, branch, len(desired_blobs), len(deletes), message,
    )
    return True


def _ensure_branch(repo: str, branch: str) -> None:
    """Create ``branch`` from ``main`` if it doesn't exist. Idempotent."""
    status, body = _gh_status("GET", f"/repos/{GITHUB_OWNER}/{repo}/git/refs/heads/{branch}")
    if status == 200:
        return
    if status == 404:
        main_ref = _gh("GET", f"/repos/{GITHUB_OWNER}/{repo}/git/refs/heads/main")
        _gh(
            "POST",
            f"/repos/{GITHUB_OWNER}/{repo}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": main_ref["object"]["sha"]},
        )
        logger.info("[%s] created branch %s from main", repo, branch)
        return
    detail = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)
    raise RuntimeError(f"GET refs/heads/{branch} on {repo} -> HTTP {status}: {detail}")


# --------------------------------------------------------------------------- #
# Removal bookkeeping (update-embedded removals; env-scoped delete)
# --------------------------------------------------------------------------- #

def _capability_slugs(config: dict) -> list[str]:
    """The extract slug(s) a capability config produces.

    Mirrors Step-2 ``_claims_for`` so removals target exactly the file names
    extract committed: ``rel_database`` -> ``_slug(name)``, ``storage`` ->
    ``storage``, ``messaging`` -> one slug per queue plus ``notification``
    when configured.
    """
    cap_type = config.get("type")
    if cap_type == "rel_database":
        return [_slug(config.get("name") or "db")]
    if cap_type == "storage":
        return ["storage"]
    if cap_type == "messaging":
        slugs = [
            _slug((queue or {}).get("name") or "default")
            for queue in config.get("queue") or []
        ]
        if config.get("notification"):
            slugs.append("notification")
        return slugs
    return []


def _removed_slugs_by_env(
    capabilities: list[dict],
    updates: list[dict],
) -> dict[str, set[str]]:
    """Capability slugs an update removes, keyed by environment.

    ``capabilities`` is the request-details capability list (each carries its
    ``config`` and the derived ``environment``); ``updates`` is the update
    request's raw entries with their ``remove_capabilities`` type lists.
    """
    removed_types_by_env = {
        (u.get("env") or ""): set(u.get("remove_capabilities") or [])
        for u in updates
    }
    if not any(removed_types_by_env.values()):
        return {}
    slugs_by_env: dict[str, set[str]] = {}
    for cap in capabilities:
        env = cap.get("environment") or ""
        if cap.get("capabilityType") not in removed_types_by_env.get(env, set()):
            continue
        for slug in _capability_slugs(cap.get("config") or {}):
            slugs_by_env.setdefault(env, set()).add(slug)
    return slugs_by_env


def _fully_removed_bases(
    services: list[dict],
    environments: list[str],
    updates: list[dict],
) -> set[str]:
    """Bases an update removes from every environment they exist in.

    A fully-removed base loses its shared ``argocd/apps/<app>/apps/<base>/``
    folder and its CI workflow; a base removed from only some environments
    keeps them (the remaining envs still deploy it). The services-monorepo
    folder is user code and stays either way.
    """
    removed_by_env = {
        (u.get("env") or ""): set(u.get("remove_services") or [])
        for u in updates
    }
    if not any(removed_by_env.values()):
        return set()

    envs_with_rows: dict[str, set[str]] = {}
    for svc in services:
        base = _strip_env(svc["svcName"], environments)
        env = svc["svcName"][len(base) + 1:] if svc["svcName"] != base else ""
        envs_with_rows.setdefault(base, set()).add(env)

    return {
        base
        for base, envs in envs_with_rows.items()
        if envs and all(base in removed_by_env.get(env, set()) for env in envs)
    }


# --------------------------------------------------------------------------- #
# Services monorepo
# --------------------------------------------------------------------------- #

def _strip_env(svc_name: str, environments: list[str]) -> str:
    """``orders-api-qa`` -> ``orders-api`` (longest env suffix wins).

    Strips both the control-plane environments and the canonical gitops envs,
    so legacy ``orders-api-dev`` rows still deduplicate to ``orders-api``.
    """
    candidates = sorted(set(environments) | set(GITOPS_ENVIRONMENTS), key=len, reverse=True)
    for env in candidates:
        suffix = f"-{env}"
        if svc_name.endswith(suffix):
            return svc_name[: -len(suffix)]
    return svc_name


_SERVICES_GITIGNORE = """\
.env
*.log
.venv/
venv/
node_modules/
target/
__pycache__/
"""


def _services_repo_files(
    app_name: str,
    base_services: dict,
    gitops_repo: str,
) -> dict[str, str]:
    files = {}

    lines = ["# " + app_name, "", "Services monorepo generated by Makeway.", "", "## Services"]
    files[".gitignore"] = _SERVICES_GITIGNORE

    for base, spec in base_services.items():
        lines.append(f"- `{base}` — golden-path `{spec['stack']}` service")

        stack_dir = STACK_TEMPLATE_DIR.get(spec["stack"])
        if stack_dir is None:
            logger.warning("no template for stack %s (%s)", spec["stack"], base)
            continue

        for rel_path, content in _collect_template_files(
            os.path.join(TEMPLATES_DIR, stack_dir)
        ).items():
            files[f"{base}/{rel_path}"] = _render(
                content, SERVICE_NAME=base, APP_NAME=app_name
            )

        # Per-service CI workflow lives at the repo root (GitHub only scans
        # .github/workflows at the root) and is path-filtered to this service.
        ci_path = f".github/workflows/ci-{base}.yaml"
        with open(os.path.join(CI_TEMPLATES_DIR, "ci-service.yaml"), "r", encoding="utf-8") as handle:
            files[ci_path] = _render(
                handle.read(),
                SERVICE_NAME=base,
                APP_NAME=app_name,
                GITOPS_REPO=gitops_repo,
            )

    files["README.md"] = "\n".join(lines) + "\n"
    return files


def _push_services_repo(
    services_repo: str,
    app_name: str,
    base_services: dict,
    gitops_repo: str,
    delete_paths: list[str] | tuple[str, ...] = (),
) -> None:
    files = _services_repo_files(app_name, base_services, gitops_repo)
    _push_tree(
        services_repo,
        files,
        f"makeway: scaffold {app_name} services (golden-path + CI)",
        delete_paths=delete_paths,
    )


# --------------------------------------------------------------------------- #
# GitOps — argocd/apps/<appName>/ inside the Makeway platform repo
# --------------------------------------------------------------------------- #

def _insert_line_after_marker(text: str, marker: str, line: str) -> str:
    """Insert ``line`` right after a list header like ``resources:`` (idempotent)."""
    if line in text:
        return text
    marker_line = f"{marker}:\n"
    if marker_line in text:
        return text.replace(marker_line, marker_line + line + "\n")
    return text.rstrip("\n") + "\n" + line + "\n"


def _preserve_gitops_extras(
    rendered: str,
    current: str | None,
    exclude_slugs: set[str] | frozenset[str] = frozenset(),
) -> str:
    """Carry Step-2 extract's kustomization entries across regeneration.

    Extract appends ``inject/<slug>-env.yaml`` patch lines and
    ``external-secrets/<slug>-external-secret.yaml`` resource lines to each
    env overlay's kustomization.yaml. When Step-1 re-renders the overlay (a
    retry, or an app update that re-scaffolds), the regenerated content would
    silently drop those entries — the PR would then remove them from main and
    ArgoCD would briefly deploy without capability secret injection. This
    carries them over: any ``inject/`` or ``external-secrets/`` line present
    in ``current`` but missing from ``rendered`` is re-inserted after its
    marker. ``current=None`` (first creation) is a no-op.

    ``exclude_slugs`` drops the entries of capabilities an update removes —
    their extract files are deleted in the same push.
    """
    if not current:
        return rendered
    for line in current.splitlines():
        stripped = line.strip()
        if any(
            f"inject/{slug}-env.yaml" in stripped
            or f"external-secrets/{slug}-external-secret.yaml" in stripped
            for slug in exclude_slugs
        ):
            continue
        if stripped.startswith("- external-secrets/"):
            rendered = _insert_line_after_marker(rendered, "resources", line)
        elif stripped.startswith("- path: inject/"):
            rendered = _insert_line_after_marker(rendered, "patches", line)
    return rendered


def _argocd_app_files(
    app_name: str,
    base_services: dict,
    removed_bases_by_env: dict[str, set[str]] | None = None,
    removed_slugs_by_env: dict[str, set[str]] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Build the argocd/apps/<appName>/ tree (base/apps/envs layout).

    Envs come from the canonical ``GITOPS_ENVIRONMENTS`` (qa/uat/prod), not
    the control-plane cluster list — every app gets one overlay per tier, and
    each is maintained by a specific branch in the service's CI.

    Removal support (update flow): ``removed_bases_by_env`` names the bases an
    update drops from a specific environment — they lose that env's overlay
    entries and patch file while other envs keep them. ``removed_slugs_by_env``
    names the capability slugs (extract's derivation) whose inject/
    external-secrets entries must not be carried back into the regenerated
    kustomizations.

    Returns ``(files, delete_paths)`` — the upsert set and the blob paths /
    prefixes to delete from the platform repo in the same push.
    """
    prefix = f"argocd/apps/{app_name}/"
    removed_bases_by_env = removed_bases_by_env or {}
    removed_slugs_by_env = removed_slugs_by_env or {}
    templates = _collect_template_files(GITOPS_TEMPLATES_DIR)
    files: dict[str, str] = {}
    delete_paths: list[str] = []

    files[prefix + "README.md"] = _render(templates["README.md"], APP_NAME=app_name)

    # base/ holds what every env overlay shares (the netpols) but NOT the
    # namespaces: each overlay creates exactly its own {app}-{env} Namespace via
    # envs/<env>/namespace.yaml, so the qa Application never manages uat/prod.
    # base/kustomization.yaml — makes base/ a kustomize root so env overlays can
    # reference it via "../../base".
    files[prefix + "base/kustomization.yaml"] = _render(
        templates["base/kustomization.yaml"], APP_NAME=app_name
    )
    # base/network-policies.yaml — default-deny ingress + allow same-namespace,
    # shipped into every env overlay so each {app}-{env} namespace isolates
    # itself from other apps' namespaces.
    files[prefix + "base/network-policies.yaml"] = _render(
        templates["base/network-policies.yaml"], APP_NAME=app_name
    )

    # apps/<base>/ — golden-path Deployment + Service + kustomization, shared
    # across environments. Image tags are overridden per env via the patches.
    for base, spec in base_services.items():
        port = STACK_PORT.get(spec["stack"])
        if port is None:
            raise RuntimeError(f"no runtime port for stack {spec['stack']} ({base})")
        image = _render(PLACEHOLDER_IMAGE, SERVICE_NAME=base)
        files[prefix + f"apps/{base}/deployment.yaml"] = _render(
            templates["apps/deployment.yaml"],
            SERVICE_NAME=base,
            PORT=str(port),
            IMAGE=image,
        )
        files[prefix + f"apps/{base}/service.yaml"] = _render(
            templates["apps/service.yaml"],
            SERVICE_NAME=base,
            PORT=str(port),
        )
        files[prefix + f"apps/{base}/kustomization.yaml"] = _render(
            templates["apps/kustomization.yaml"],
            SERVICE_NAME=base,
        )

    # envs/<env>/ — overlay: this env's own Namespace + the app's shared
    # base (netpols) + every service base, then patch each service's image tag.
    for env in GITOPS_ENVIRONMENTS:
        # Bases this update removes from THIS env keep their shared apps/<base>/
        # folder (other envs may still deploy them) but lose this env's
        # references. An env left with no bases loses its whole overlay —
        # dropping the Application makes ArgoCD cascade the namespace away.
        env_bases = [
            base for base in base_services
            if base not in removed_bases_by_env.get(env, set())
        ]
        if not env_bases:
            delete_paths.append(prefix + f"envs/{env}/")
            continue

        files[prefix + f"envs/{env}/namespace.yaml"] = _render(
            templates["envs/namespace.yaml"],
            APP_NAME=app_name,
            ENV=env,
        )
        resources = "\n".join(
            ["  - namespace.yaml", "  - ../../base"]
            + [f"  - ../../apps/{base}" for base in env_bases]
        )
        patches = "\n".join(f"  - path: {base}-patch.yaml" for base in env_bases)
        # Merge Step-2 extract's entries (inject patches + external-secrets
        # resources) back into the regenerated overlay so re-runs and updates
        # don't drop them — minus the slugs this update removes. Reads main
        # (the ArgoCD deploy branch).
        files[prefix + f"envs/{env}/kustomization.yaml"] = _preserve_gitops_extras(
            _render(
                templates["envs/kustomization.yaml"],
                APP_NAME=app_name,
                ENV=env,
                SERVICES_YAML=resources,
                PATCHES_YAML=patches,
            ),
            _git_file(
                MAKEWAY_PLATFORM_REPO,
                f"{prefix}envs/{env}/kustomization.yaml",
            ),
            exclude_slugs=removed_slugs_by_env.get(env, set()),
        )
        for base in env_bases:
            patch_path = prefix + f"envs/{env}/{base}-patch.yaml"
            # The patch file is CI-owned after the first build (CI rewrites the
            # image tag on merge to the env's branch); carry the current content
            # over rather than re-rendering the placeholder, which would clobber
            # the real tag. First creation renders the placeholder.
            files[patch_path] = _git_file(MAKEWAY_PLATFORM_REPO, patch_path) or _render(
                templates["envs/service-patch.yaml"],
                SERVICE_NAME=base,
                ENV=env,
                IMAGE=_render(PLACEHOLDER_IMAGE, SERVICE_NAME=base),
            )

    # Removed items' files go in the same push as the regenerated overlays.
    for env, bases in removed_bases_by_env.items():
        for base in bases:
            delete_paths.append(prefix + f"envs/{env}/{base}-patch.yaml")
    for env, slugs in removed_slugs_by_env.items():
        for slug in slugs:
            delete_paths.append(prefix + f"envs/{env}/inject/{slug}-env.yaml")
            delete_paths.append(
                prefix + f"envs/{env}/external-secrets/{slug}-external-secret.yaml"
            )

    return files, delete_paths


def _find_open_pr(repo: str, branch: str) -> dict | None:
    pulls = _gh(
        "GET",
        f"/repos/{GITHUB_OWNER}/{repo}/pulls",
        params={"state": "open", "head": f"{GITHUB_OWNER}:{branch}"},
    )
    return pulls[0] if pulls else None


def _create_pr(
    repo: str,
    branch: str,
    app_name: str,
    title: str | None = None,
    body: str | None = None,
) -> dict:
    return _gh(
        "POST",
        f"/repos/{GITHUB_OWNER}/{repo}/pulls",
        {
            "title": title or f"makeway: ArgoCD setup for {app_name}",
            "head": branch,
            "base": "main",
            "body": body or (
                "Generated by the Makeway app-creation flow.\n\n"
                f"Adds the ArgoCD configuration for **{app_name}** under "
                "`argocd/apps/` (base/apps/envs layout). Env overlays (qa/uat/prod) "
                "contain the image patches that each service's CI workflow updates "
                "on merge to its branch (`feature/*` → qa, `release/*` → uat, "
                "`main` → prod)."
            ),
        },
    )


def _try_merge(
    repo: str,
    pr_number: int,
    pr_url: str,
    commit_title: str = "makeway: ArgoCD setup [skip ci]",
) -> dict:
    status, body = _gh_status(
        "PUT",
        f"/repos/{GITHUB_OWNER}/{repo}/pulls/{pr_number}/merge",
        payload={
            "commit_title": commit_title,
            "merge_method": "squash",
            "delete_branch_after_merge": True,
        },
    )
    if 200 <= status < 300:
        logger.info("[%s] merged PR#%s (%s)", repo, pr_number, pr_url)
        return {"merged": True, "pr_url": pr_url}
    if status in (403, 405, 409, 422):
        # Branch protection (review required) or an already-merged/conflicted PR.
        detail = json.dumps(body)[:300] if isinstance(body, (dict, list)) else str(body)
        logger.warning(
            "[%s] PR#%s not auto-merged (HTTP %s): %s — leaving open for review",
            repo,
            pr_number,
            status,
            detail,
        )
        return {"merged": False, "pr_url": pr_url}
    detail = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)
    raise RuntimeError(f"merge PR#{pr_number} on {repo} -> HTTP {status}: {detail}")


def _publish_gitops_to_platform(
    app_name: str,
    files: dict[str, str],
    message: str,
    delete_paths: list[str] | tuple[str, ...] = (),
    pr_title: str | None = None,
    pr_body: str | None = None,
    merge_title: str = "makeway: ArgoCD setup [skip ci]",
) -> dict:
    """Commit argocd/apps/<appName>/ into the Makeway platform repo via a PR.

    The platform repo's ``main`` is the ArgoCD deploy branch, so changes land on
    a feature branch and go up as a PR that is auto-merged (squash) when GitHub
    allows it, and left open for review otherwise. ``delete_paths`` removes
    blobs/prefixes in the same commit (teardown). Idempotent: when the branch's
    tree already matches and the PR is merged, nothing is pushed.
    """
    branch = f"makeway/apps/{app_name}"
    _ensure_branch(MAKEWAY_PLATFORM_REPO, branch)
    changed = _push_tree(
        MAKEWAY_PLATFORM_REPO,
        files,
        message,
        branch=branch,
        delete_paths=delete_paths,
    )

    pr = _find_open_pr(MAKEWAY_PLATFORM_REPO, branch)
    if pr is None:
        if not changed:
            logger.info(
                "[%s] gitops for %s already on main — nothing to do",
                MAKEWAY_PLATFORM_REPO,
                app_name,
            )
            return {"merged": True, "pr_url": None}
        pr = _create_pr(MAKEWAY_PLATFORM_REPO, branch, app_name, title=pr_title, body=pr_body)

    return _try_merge(MAKEWAY_PLATFORM_REPO, pr["number"], pr["html_url"], commit_title=merge_title)


def _remove_gitops(
    app_name: str,
    prefixes: list[str],
    message: str,
    pr_title: str,
) -> dict:
    """Delete every blob under ``prefixes`` from argocd/apps/<appName>/ via a PR.

    ``prefixes`` may be exact blob paths or directory prefixes; ``_push_tree``
    expands them against the branch's current tree, so already-gone targets are
    naturally skipped (idempotent — a re-run finds nothing to delete and never
    opens a PR).
    """
    return _publish_gitops_to_platform(
        app_name,
        {},
        message,
        delete_paths=prefixes,
        pr_title=pr_title,
        merge_title="makeway: ArgoCD removal [skip ci]",
    )


# --------------------------------------------------------------------------- #
# Control-plane status callbacks
# --------------------------------------------------------------------------- #

def _report(
    request_id: int,
    job_id: int,
    status: str,
    execution_arn: str | None = None,
    error: str | None = None,
    app_repo_url: str | None = None,
    gitops_path: str | None = None,
    service_repo_paths: list[dict] | None = None,
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
    if app_repo_url:
        payload["appRepoUrl"] = app_repo_url
    if gitops_path:
        payload["gitOpsPath"] = gitops_path
    if service_repo_paths:
        payload["serviceRepoPaths"] = service_repo_paths
    _control_plane("POST", f"/internal/requests/{request_id}/status", payload)
    logger.info("reported %s for request_id=%s job_id=%s", status, request_id, job_id)


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #

def handler(event, context):
    request_id = int(event["request_id"])
    job_id = int(event.get("job_id", 0))
    execution_arn = event.get("execution_arn")

    # Fresh secret read per invocation: these module globals persist in a warm
    # execution environment, so a PAT rotated between executions would
    # otherwise keep failing with the stale cached token until AWS happened to
    # recycle the container. Within-execution caching is unaffected — one
    # secret read + one /user call per run.
    global _github_token, _git_identity_cache
    _github_token = None
    _git_identity_cache = None

    logger.info(
        "Step 1 (GitHub Setup) starting request_id=%s job_id=%s execution=%s",
        request_id,
        job_id,
        execution_arn,
    )

    try:
        details = _control_plane("GET", f"/internal/requests/{request_id}")

        # Idempotency: a retry that already succeeded must not redo the step.
        if details.get("job", {}).get("status") == "success":
            logger.info("request_id=%s job already SUCCESS — skipping Step 1", request_id)
            # This return becomes the next state's entire input, so it must
            # carry the keys the Step2 Apply payload references ($.request_id /
            # $.job_id) — a bare skipped dict would fail the state machine.
            return {
                "status": "skipped",
                "reason": "already_success",
                "request_id": request_id,
                "job_id": job_id,
            }

        _report(request_id, job_id, "in_progress", execution_arn)

        request_type = details.get("requestType")
        raw_request = details.get("rawRequest") or {}
        app = details["app"]
        services = details["services"]
        environments = details.get("environments") or []
        app_name = app["appName"]
        services_repo = app_name

        if request_type == REQUEST_TYPE_DELETE:
            # Env-scoped teardown: strip the env's GitOps overlay so the
            # ApplicationSet drops the Application and ArgoCD cascades the
            # namespace (with its ExternalSecrets and connection secrets) away.
            # Crossplane tears the AWS resources down in Step 2. When this is
            # the app's last environment, strip the whole argocd/apps/<app>/
            # tree — the App record and the services monorepo stay.
            env = raw_request.get("env")
            remaining = [e for e in environments if e != env]
            if remaining:
                prefix = f"argocd/apps/{app_name}/envs/{env}/"
                pr_title = f"makeway: remove ArgoCD setup for {app_name} ({env})"
            else:
                prefix = f"argocd/apps/{app_name}/"
                pr_title = f"makeway: remove ArgoCD setup for {app_name}"

            publish = _remove_gitops(
                app_name,
                prefixes=[prefix],
                message=pr_title,
                pr_title=pr_title,
            )
            gitops_path = prefix

            _report(request_id, job_id, "success", execution_arn, gitops_path=gitops_path)
            logger.info(
                "Step 1 succeeded (delete env=%s) request_id=%s gitops=%s (merged=%s pr=%s)",
                env, request_id, gitops_path, publish["merged"], publish.get("pr_url"),
            )
            return {
                "status": "success",
                "request_id": request_id,
                "job_id": job_id,
                "gitops_path": gitops_path,
                "gitops_pr_url": publish.get("pr_url"),
            }

        updates = raw_request.get("updates") or []
        removed_bases_by_env = {
            (u.get("env") or ""): set(u.get("remove_services") or [])
            for u in updates
            if u.get("remove_services")
        }
        removed_slugs_by_env = _removed_slugs_by_env(
            details.get("capabilities") or [], updates
        )
        fully_removed = _fully_removed_bases(services, environments, updates)

        base_services: dict[str, dict] = {}
        for svc in services:
            base = _strip_env(svc["svcName"], environments)
            if base in fully_removed:
                continue
            base_services.setdefault(base, {"stack": svc["serviceType"], "rows": []})
            base_services[base]["rows"].append(svc)

        if not base_services:
            # Every service was removed — the app has nothing left to deploy,
            # so its whole GitOps tree goes (same as a last-environment delete).
            # The control plane purges the rows on SUCCESS.
            publish = _remove_gitops(
                app_name,
                prefixes=[f"argocd/apps/{app_name}/"],
                message=f"makeway: remove ArgoCD setup for {app_name} (no services left)",
                pr_title=f"makeway: remove ArgoCD setup for {app_name}",
            )
            gitops_path = f"argocd/apps/{app_name}/"

            _report(request_id, job_id, "success", execution_arn, gitops_path=gitops_path)
            logger.info(
                "Step 1 succeeded (all services removed) request_id=%s gitops=%s (merged=%s pr=%s)",
                request_id, gitops_path, publish["merged"], publish.get("pr_url"),
            )
            return {
                "status": "success",
                "request_id": request_id,
                "job_id": job_id,
                "gitops_path": gitops_path,
                "gitops_pr_url": publish.get("pr_url"),
            }

        # 1. Services monorepo: golden-path folders + per-service CI. The
        #    monorepo folders of fully-removed services are user code — left
        #    in place; their CI workflows lose their gitops target and go.
        _ensure_repo(services_repo)
        _push_services_repo(
            services_repo,
            app_name,
            base_services,
            PLATFORM_REPO,
            delete_paths=[
                f".github/workflows/ci-{base}.yaml" for base in sorted(fully_removed)
            ],
        )

        # 2. GitOps: argocd/apps/<appName>/ inside the Makeway platform repo.
        #    Envs are the canonical qa/uat/prod tiers (no dev).
        gitops_files, gitops_deletes = _argocd_app_files(
            app_name,
            base_services,
            removed_bases_by_env=removed_bases_by_env,
            removed_slugs_by_env=removed_slugs_by_env,
        )
        for base in sorted(fully_removed):
            gitops_deletes.append(f"argocd/apps/{app_name}/apps/{base}/")
        gitops_message = (
            f"makeway: add ArgoCD setup for {app_name} (base/apps/envs)"
            if not updates
            else f"makeway: update ArgoCD setup for {app_name} (base/apps/envs)"
        )
        publish = _publish_gitops_to_platform(
            app_name,
            gitops_files,
            gitops_message,
            delete_paths=gitops_deletes,
        )

        app_repo_url = f"https://github.com/{GITHUB_OWNER}/{services_repo}"
        gitops_repo_url = f"https://github.com/{PLATFORM_REPO}"
        gitops_path = f"argocd/apps/{app_name}/"
        service_repo_paths = [
            {"svcId": svc["svcId"], "repoPath": _strip_env(svc["svcName"], environments)}
            for svc in services
        ]

        _report(
            request_id,
            job_id,
            "success",
            execution_arn,
            app_repo_url=app_repo_url,
            gitops_path=gitops_path,
            service_repo_paths=service_repo_paths,
        )

        logger.info(
            "Step 1 succeeded request_id=%s repos=%s gitops=%s (merged=%s pr=%s)",
            request_id,
            app_repo_url,
            gitops_repo_url,
            publish["merged"],
            publish.get("pr_url"),
        )
        return {
            "status": "success",
            "request_id": request_id,
            "job_id": job_id,
            "app_repo_url": app_repo_url,
            "gitops_repo_url": gitops_repo_url,
            "gitops_path": gitops_path,
            "gitops_pr_url": publish.get("pr_url"),
        }

    except Exception as exc:  # noqa: BLE001 — report and re-raise for SFN retry
        logger.exception("Step 1 failed request_id=%s", request_id)
        try:
            _report(request_id, job_id, "failed", execution_arn, error=str(exc)[:2000])
        except Exception as report_error:  # noqa: BLE001
            logger.warning("failed to report failure to control plane: %s", report_error)
        raise