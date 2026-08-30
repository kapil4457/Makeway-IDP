"""Pure-logic smoke test for the Step-2 handler (no network, no AWS).

Covers: template parser over every XR template, capability expansion for all
four capability types, storage bucket-name length cap, kustomization insert +
idempotency, per-type IAM policies, and claim token rendering.
Run:  python _smoke_step2.py
"""
import importlib.util
import os
import sys
from pathlib import Path

# The handler reads its configuration at import time — supply dummy values so
# the pure functions are testable without a live environment.
os.environ.setdefault("CONTROL_PLANE_URL", "http://localhost:8000")
os.environ.setdefault("INTERNAL_API_KEY", "test-key")
os.environ.setdefault("KUBE_API_ENDPOINT", "https://127.0.0.1:6443")
os.environ.setdefault("KUBE_TOKEN", "test-token")
os.environ.setdefault("GITHUB_OWNER", "kapil4457")
os.environ.setdefault("GITHUB_TOKEN_SECRET_ID", "makeway/test-github-pat")
os.environ.setdefault("MAKEWAY_PLATFORM_REPO", "kapil4457/Makeway-IDP")
os.environ.setdefault("DEFAULT_REGION", "ap-south-1")

H = Path(__file__).resolve().parent / "handler.py"
spec = importlib.util.spec_from_file_location("step2", H)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# 1. parser over every XR template (external-secret.yaml is parsed as text,
#    never through the template parser -- extract hands it to _render + git push).
for t in sorted(Path("claim_templates").glob("*.yaml")):
    if t.name == "external-secret.yaml":
        continue
    data = m._parse_claim_yaml(t.read_text())
    check(
        f"parse {t.name}: kind/name",
        isinstance(data, dict)
        and data.get("metadata", {}).get("name")
        and data.get("apiVersion"),
    )

# 2. capability -> claim expansion for all three types. The dicts mirror what
#    control-plane get_request_details returns: namespace = {app}-{env}.
caps = [
    {"capabilityType": "rel_database", "config": {"name": "orders"}, "environment": "qa", "namespace": "order-service-qa", "capabilityId": "cap-rds"},
    {"capabilityType": "storage", "config": {"s3": {"region": "ap-south-1"}}, "environment": "qa", "namespace": "order-service-qa", "capabilityId": "cap-storage"},
    {
        "capabilityType": "messaging",
        "config": {"queue": [{"name": "orders"}], "notification": True},
        "environment": "qa",
        "namespace": "order-service-qa",
        "capabilityId": "cap-msg",
    },
]
expected = {"rel_database": 1, "storage": 1, "messaging": 2}
for cap in caps:
    claims = m._claims_for("order-service", cap, "123456789012")
    check(
        f"claims[{cap['capabilityType']}] count == {expected[cap['capabilityType']]}",
        len(claims) == expected[cap["capabilityType"]],
        f"got {len(claims)}",
    )

# 3. storage bucket-name length cap (k8s/object storage limits: <=63 chars)
#    bucket lives in the claim's render tokens (BUCKET_NAME), and the S3 name
#    Crossplane writes back as the connection-secret key is `bucketName`.
st = m._claims_for("order-service", caps[1], "123456789012")[0]
bucket = st["tokens"]["BUCKET_NAME"]
check("storage bucket <=63 chars", len(bucket) <= 63, bucket)
check("storage bucket kebab", bucket == bucket.lower())
check("storage bucket prefix", bucket.startswith("order-service-qa-"), bucket)

# 4. kustomization resource insert + idempotency, decoding the git blob shape
base = "resources:\n  - ../../base\n  - ../../apps/orders-api\npatches:\n  - path: orders-api-patch.yaml\n"
once = m._add_kustomization_resource(base, "external-secrets/orders-external-secret.yaml")
twice = m._add_kustomization_resource(once, "external-secrets/orders-external-secret.yaml")
check(
    "kustomize insert before patches",
    "  - external-secrets/orders-external-secret.yaml\npatches:" in once,
)
check("kustomize idempotent", once == twice)

# 5. RDS manifest is a v2 XR (kind without the Claim suffix, compositionRef
#    under spec.crossplane) carrying the local-cluster seam (publiclyAccessible
#    + cidr). The claim dict stores the template/tokens; the parsed manifest
#    comes from _claim_manifest(claim) — the same call apply/extract use.
rds = m._claims_for("order-service", caps[0], "123456789012")[0]
claim_manifest = m._claim_manifest(rds)
check("rds claim manifest dict", isinstance(claim_manifest, dict))
if isinstance(claim_manifest, dict):
    check("rds manifest kind is XR (v2)", claim_manifest.get("kind") == "RelationalDatabase")
    crossplane = claim_manifest.get("spec", {}).get("crossplane", {})
    check(
        "rds compositionRef under spec.crossplane",
        crossplane.get("compositionRef", {}).get("name") == "relational-database.aws",
    )
    params = claim_manifest.get("spec", {}).get("parameters", {})
    check(
        "rds publiclyAccessible rendered",
        params.get("publiclyAccessible") is True or params.get("publiclyAccessible") is False,
    )
    check("rds ingressSourceCidr rendered", params.get("ingressSourceCidr") is not None)
    check("rds conn secret name", rds.get("conn_secret", "").endswith("-connection-details"))
    labels = claim_manifest.get("metadata", {}).get("labels", {})
    check("capability-id label is str", isinstance(labels.get("capability-id"), str))

# 6. ExternalSecret rendered text — what extract actually commits for ESO
#    (the claim parser never sees this template; extract hands the rendered
#    text to the gitops push, so test exactly that path).
es_text = m._render(
    (Path("claim_templates") / "external-secret.yaml").read_text(),
    TARGET_NAME="orders-service-creds",
    NAMESPACE="order-service-qa",
    SM_SECRET_NAME="makeway/order-service/qa/creds",
)
check("es secretStoreRef makeway/ClusterSecretStore",
      "name: makeway" in es_text and "kind: ClusterSecretStore" in es_text)
check("es dataFrom extract key",
      "key: makeway/order-service/qa/creds" in es_text
      and "extract:" in es_text)
check("es target name + namespace",
      "name: orders-service-creds" in es_text
      and "namespace: order-service-qa" in es_text)

# 7. IAM policies per type. _aws_policy(claim, conn) reads real claim dicts
#    and the connection-secret keys Crossplane's compositions write.
pol_storage = m._aws_policy(st, {"bucketName": bucket})
check("storage policy s3 actions", "s3:" in str(pol_storage) and "s3:ListBucket" in str(pol_storage))
q_claim = [c for c in m._claims_for("order-service", caps[2], "123456789012") if c["slug"] != "notification"][0]
pol_queue = m._aws_policy(
    q_claim,
    {
        "queueUrl": "https://sqs.ap-south-1.amazonaws.com/123456789012/orders",
        "queueArn": "arn:aws:sqs:ap-south-1:123456789012:orders",
        "dlqArn": "arn:aws:sqs:ap-south-1:123456789012:orders-dlq",
    },
)
check("queue policy sqs actions", "sqs:" in str(pol_queue) and str(pol_queue).count("arn:") >= 2)
n_claim = [c for c in m._claims_for("order-service", caps[2], "123456789012") if c["slug"] == "notification"][0]
pol_sns = m._aws_policy(n_claim, {"topicArn": "arn:aws:sns:ap-south-1:123456789012:order-service-qa-notification"})
check("sns policy publish action", "sns:Publish" in str(pol_sns) and "arn:aws:sns" in str(pol_sns))

print()
if fails:
    sys.exit("FAILED: " + ", ".join(fails))
print("step2 handler smoke: ALL PASS")