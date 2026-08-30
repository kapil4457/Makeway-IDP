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

Idempotency: repo existence is checked first (``GET /repos/{owner}/{repo}``)
and the tree push diffs against the current git tree, so re-running skips no-op
commits and reuses the existing feature branch. If the job already reached
``success``, the handler exits early.
"""

import json
import logging
import os
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


def _push_tree(repo: str, files: dict[str, str], message: str, branch: str = "main") -> bool:
    """Commit ``files`` ({path: content}) to ``branch`` via the git database API.

    Re-running with the same content produces no new commit (the desired tree
    is diffed against the current tree before anything is written). Returns
    whether a new commit was made.
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
        if current_blobs.get(path) is not None:
            continue
        blob = _gh(
            "POST",
            f"/repos/{GITHUB_OWNER}/{repo}/git/blobs",
            {"content": content, "encoding": "utf-8"},
        )
        desired_blobs[path] = blob["sha"]

    if not desired_blobs:
        logger.info("[%s/%s] no changes to push — already at desired tree", repo, branch)
        return False

    tree_entries = [
        {"path": path, "mode": "100644", "type": "blob", "sha": sha}
        for path, sha in desired_blobs.items()
    ]
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
    logger.info("[%s/%s] pushed %d files (%s)", repo, branch, len(desired_blobs), message)
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


def _push_services_repo(services_repo: str, app_name: str, base_services: dict, gitops_repo: str) -> None:
    files = _services_repo_files(app_name, base_services, gitops_repo)
    _push_tree(
        services_repo,
        files,
        f"makeway: scaffold {app_name} services (golden-path + CI)",
    )


# --------------------------------------------------------------------------- #
# GitOps — argocd/apps/<appName>/ inside the Makeway platform repo
# --------------------------------------------------------------------------- #

def _argocd_app_files(
    app_name: str,
    base_services: dict,
) -> dict[str, str]:
    """Build the argocd/apps/<appName>/ tree (base/apps/envs layout).

    Envs come from the canonical ``GITOPS_ENVIRONMENTS`` (qa/uat/prod), not
    the control-plane cluster list — every app gets one overlay per tier, and
    each is maintained by a specific branch in the service's CI.
    """
    prefix = f"argocd/apps/{app_name}/"
    templates = _collect_template_files(GITOPS_TEMPLATES_DIR)
    files = {}

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
        files[prefix + f"envs/{env}/namespace.yaml"] = _render(
            templates["envs/namespace.yaml"],
            APP_NAME=app_name,
            ENV=env,
        )
        resources = "\n".join(
            ["  - namespace.yaml", "  - ../../base"]
            + [f"  - ../../apps/{base}" for base in base_services]
        )
        patches = "\n".join(f"  - path: {base}-patch.yaml" for base in base_services)
        files[prefix + f"envs/{env}/kustomization.yaml"] = _render(
            templates["envs/kustomization.yaml"],
            APP_NAME=app_name,
            ENV=env,
            SERVICES_YAML=resources,
            PATCHES_YAML=patches,
        )
        for base in base_services:
            files[prefix + f"envs/{env}/{base}-patch.yaml"] = _render(
                templates["envs/service-patch.yaml"],
                SERVICE_NAME=base,
                ENV=env,
                IMAGE=_render(PLACEHOLDER_IMAGE, SERVICE_NAME=base),
            )

    return files


def _find_open_pr(repo: str, branch: str) -> dict | None:
    pulls = _gh(
        "GET",
        f"/repos/{GITHUB_OWNER}/{repo}/pulls",
        params={"state": "open", "head": f"{GITHUB_OWNER}:{branch}"},
    )
    return pulls[0] if pulls else None


def _create_pr(repo: str, branch: str, app_name: str) -> dict:
    return _gh(
        "POST",
        f"/repos/{GITHUB_OWNER}/{repo}/pulls",
        {
            "title": f"makeway: ArgoCD setup for {app_name}",
            "head": branch,
            "base": "main",
            "body": (
                "Generated by the Makeway app-creation flow.\n\n"
                f"Adds the ArgoCD configuration for **{app_name}** under "
                "`argocd/apps/` (base/apps/envs layout). Env overlays (qa/uat/prod) "
                "contain the image patches that each service's CI workflow updates "
                "on merge to its branch (`feature/*` → qa, `release/*` → uat, "
                "`main` → prod)."
            ),
        },
    )


def _try_merge(repo: str, pr_number: int, pr_url: str) -> dict:
    status, body = _gh_status(
        "PUT",
        f"/repos/{GITHUB_OWNER}/{repo}/pulls/{pr_number}/merge",
        payload={
            "commit_title": f"makeway: ArgoCD setup [skip ci]",
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


def _publish_gitops_to_platform(app_name: str, files: dict[str, str], message: str) -> dict:
    """Commit argocd/apps/<appName>/ into the Makeway platform repo via a PR.

    The platform repo's ``main`` is the ArgoCD deploy branch, so changes land on
    a feature branch and go up as a PR that is auto-merged (squash) when GitHub
    allows it, and left open for review otherwise. Idempotent: when the branch's
    tree already matches and the PR is merged, nothing is pushed.
    """
    branch = f"makeway/apps/{app_name}"
    _ensure_branch(MAKEWAY_PLATFORM_REPO, branch)
    changed = _push_tree(MAKEWAY_PLATFORM_REPO, files, message, branch=branch)

    pr = _find_open_pr(MAKEWAY_PLATFORM_REPO, branch)
    if pr is None:
        if not changed:
            logger.info(
                "[%s] gitops for %s already on main — nothing to do",
                MAKEWAY_PLATFORM_REPO,
                app_name,
            )
            return {"merged": True, "pr_url": None}
        pr = _create_pr(MAKEWAY_PLATFORM_REPO, branch, app_name)

    return _try_merge(MAKEWAY_PLATFORM_REPO, pr["number"], pr["html_url"])


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
            return {"status": "skipped", "reason": "already_success"}

        _report(request_id, job_id, "in_progress", execution_arn)

        app = details["app"]
        services = details["services"]
        environments = details.get("environments") or []

        base_services: dict[str, dict] = {}
        for svc in services:
            base = _strip_env(svc["svcName"], environments)
            base_services.setdefault(base, {"stack": svc["serviceType"], "rows": []})
            base_services[base]["rows"].append(svc)

        app_name = app["appName"]
        services_repo = app_name

        # 1. Services monorepo: golden-path folders + per-service CI.
        _ensure_repo(services_repo)
        _push_services_repo(services_repo, app_name, base_services, PLATFORM_REPO)

        # 2. GitOps: argocd/apps/<appName>/ inside the Makeway platform repo.
        #    Envs are the canonical qa/uat/prod tiers (no dev).
        gitops_files = _argocd_app_files(app_name, base_services)
        publish = _publish_gitops_to_platform(
            app_name,
            gitops_files,
            f"makeway: add ArgoCD setup for {app_name} (base/apps/envs)",
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