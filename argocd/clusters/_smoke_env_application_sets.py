"""Static contract check for the per-env ApplicationSet templates (qa/uat/prod).

`spec.goTemplate: true` switches ApplicationSet substitution to Go's
text/template engine. The legacy fasttemplate forms — `{{ path }}`,
`{{ path[2] }}` — do NOT parse: Go rejects the bracket with
"template: base:1: bad character U+005B '['" and the controller logs
"generated 0 applications". Latent from the 2026-08-31 bootstrap until the
first app dir (argocd/apps/test-app-6) reached main on 2026-09-13.

The goTemplate forms are `{{ .path.path }}` (full path) and
`{{ index .path.segments N }}` (segments of argocd/apps/<app>/envs/<env>:
0=argocd 1=apps 2=<app> 3=envs 4=<env>).

Enforced per argocd/clusters/<env>/env-application-set.yaml:
  1. goTemplate is true and every `{{ ... }}` expression in spec.template uses
     the goTemplate grammar (leading-dot path params or `index .path.segments N`).
  2. Rendering against the real git-generator params (the exact param dump from
     the production incident log) produces the expected Application name,
     app label, overlay path, and destination namespace.
  3. The validator rejects the legacy fasttemplate forms — a revert re-fails
     here instead of silently generating 0 applications.

Run:  python argocd/clusters/_smoke_env_application_sets.py   (exit 0 = holds)
"""
import re
import sys
from pathlib import Path

import yaml

CLUSTERS_DIR = Path(__file__).resolve().parent
ENVS = ["qa", "uat", "prod"]

PARAM_RE = re.compile(r"^\.(path\.path|path\.basename|path\.basenameNormalized|path\.filename|path\.filenameNormalized)$")
INDEX_RE = re.compile(r"^index \.path\.segments (0|[1-9][0-9]*)$")
EXPR_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def _expr_value(expr, segments, path):
    """Evaluate one whitelisted goTemplate expression against git-generator params."""
    m = INDEX_RE.match(expr)
    if m:
        return segments[int(m.group(1))]
    if expr == ".path.path":
        return path
    if expr == ".path.basename":
        return segments[-1]
    if expr == ".path.basenameNormalized":
        return segments[-1]
    if expr == ".path.filename":
        return segments[-1]
    if expr == ".path.filenameNormalized":
        return segments[-1]
    raise ValueError(f"expression '{expr}' is outside the goTemplate grammar")


def _validate_and_render(node, segments, path, where):
    """Grammar-check + render every {{ }} in template node. Returns rendered copy."""
    if isinstance(node, str):
        if "{{" not in node:
            return node
        for expr in EXPR_RE.findall(node):
            _expr_value(expr, segments, path)  # raises on grammar violation
        return EXPR_RE.sub(_sub(segments, path), node)
    if isinstance(node, dict):
        return {k: _validate_and_render(v, segments, path, f"{where}.{k}") for k, v in node.items()}
    if isinstance(node, list):
        return [_validate_and_render(v, segments, path, f"{where}[{i}]") for i, v in enumerate(node)]
    return node


def _sub(segments, path):
    def _do(m):
        return _expr_value(m.group(1), segments, path)
    return _do


def _walk_strings(node, where="template"):
    """Yield (field_path, string) for every string leaf carrying a template expr."""
    if isinstance(node, str) and "{{" in node:
        yield where, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_strings(v, f"{where}[{i}]")


for env in ENVS:
    file_path = CLUSTERS_DIR / env / "env-application-set.yaml"
    doc = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    tag = f"[{env}]"

    check(f"{tag} kind/name", doc["kind"] == "ApplicationSet" and doc["metadata"]["name"] == f"makeway-apps-{env}")
    check(f"{tag} goTemplate is true", doc["spec"].get("goTemplate") is True)
    glob = doc["spec"]["generators"][0]["git"]["directories"][0]["path"]
    check(f"{tag} glob targets this env", glob == f"argocd/apps/*/envs/{env}", glob)

    template = doc["spec"]["template"]

    # Rule 1: every expression uses the goTemplate grammar.
    bad = []
    for field, text in _walk_strings(template):
        for expr in EXPR_RE.findall(text):
            if not (PARAM_RE.match(expr) or INDEX_RE.match(expr)):
                bad.append(f"{field}: '{{{{ {expr} }}}}'")
    check(f"{tag} all template expressions use goTemplate grammar", not bad, "; ".join(bad))

    # Rule 2: render against the params from the real incident log.
    segments = ["argocd", "apps", "test-app-6", "envs", env]
    path = f"argocd/apps/test-app-6/envs/{env}"
    rendered = _validate_and_render(template, segments, path, f"template[{env}]")
    check(f"{tag} name renders to test-app-6-{env}", rendered["metadata"]["name"] == f"test-app-6-{env}",
          rendered["metadata"]["name"])
    check(f"{tag} app label renders to test-app-6", rendered["metadata"]["labels"]["app"] == "test-app-6",
          rendered["metadata"]["labels"]["app"])
    check(f"{tag} environment label is {env}", rendered["metadata"]["labels"]["environment"] == env)
    check(f"{tag} source.path renders to the {env} overlay", rendered["spec"]["source"]["path"] == path,
          rendered["spec"]["source"]["path"])
    check(f"{tag} destination namespace renders to test-app-6-{env}",
          rendered["spec"]["destination"]["namespace"] == f"test-app-6-{env}",
          rendered["spec"]["destination"]["namespace"])
    check(f"{tag} destination stays on the local cluster",
          rendered["spec"]["destination"]["server"] == "https://kubernetes.default.svc")
    check(f"{tag} auto-sync with prune+selfHeal survives",
          rendered["spec"]["syncPolicy"]["automated"] == {"prune": True, "selfHeal": True})

# Rule 3: the validator must reject the legacy fasttemplate forms (and near-misses).
must_reject = [
    ("legacy bracket index", "{{ path[2] }}"),
    ("legacy bare path", "{{ path }}"),
    ("legacy no-leading-dot param", "{{ path.basename }}"),
    ("index without a number", "{{ index .path.segments }}"),
    ("bracket on a dotted param", "{{ .path[2] }}"),
]
for label, sample in must_reject:
    expr = EXPR_RE.match(sample).group(1)
    try:
        _expr_value(expr, ["argocd", "apps", "app", "envs", "qa"], "argocd/apps/app/envs/qa")
        check(f"validator rejects {label}", False, "accepted")
    except ValueError:
        check(f"validator rejects {label}", True)

print()
if fails:
    sys.exit("FAILED: " + ", ".join(fails))
print("env application-set contract: ALL PASS (goTemplate grammar + render + legacy rejection)")
