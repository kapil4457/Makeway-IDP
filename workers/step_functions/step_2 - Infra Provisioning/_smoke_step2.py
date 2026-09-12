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
os.environ.setdefault("PLATFORM_VPC_PARAMETER", "/makeway/platform/vpc")

H = Path(__file__).resolve().parent / "handler.py"
spec = importlib.util.spec_from_file_location("step2", H)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# _platform_vpc() calls SSM on first use — pre-seed the cache so the pure
# claim-building paths below never leave the process.
m._platform_vpc_cache = {
    "vpc_id": "vpc-test",
    "subnet_ids": ["subnet-aaaa", "subnet-bbbb"],
    "cidr": "10.0.0.0/16",
}

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

# 2b. per-environment kube routing: claims carry the cluster the capability
#     belongs to (endpoint/token/CA from the registry). A capability dict
#     without those keys yields None, so _kube falls back to the Lambda globals.
kube_cap = {
    "capabilityType": "storage",
    "config": {"s3": {"region": "ap-south-1"}},
    "environment": "prod",
    "namespace": "order-service-prod",
    "capabilityId": "cap-storage-prod",
    "kubeApiEndpoint": "https://k8s.prod",
    "kubeToken": "prod-token",
    "kubeCaCert": "prod-ca",
}
k = m._claims_for("order-service", kube_cap, "123456789012")[0]
check("claim carries environment", k.get("environment") == "prod", str(k.get("environment")))
check("claim carries kube_endpoint", k.get("kube_endpoint") == "https://k8s.prod", str(k.get("kube_endpoint")))
check("claim carries kube_token", k.get("kube_token") == "prod-token", str(k.get("kube_token")))
check("claim carries kube_ca_cert", k.get("kube_ca_cert") == "prod-ca", str(k.get("kube_ca_cert")))

b = m._claims_for("order-service", caps[1], "123456789012")[0]
check("no kube keys -> None endpoint", b.get("kube_endpoint") is None, str(b.get("kube_endpoint")))
check("no kube keys -> None token", b.get("kube_token") is None, str(b.get("kube_token")))
check("no kube keys -> None ca_cert", b.get("kube_ca_cert") is None, str(b.get("kube_ca_cert")))

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
    check(
        "rds ingressSourceCidr derived from SSM cidr",
        params.get("ingressSourceCidr") == "10.0.0.0/16",
        str(params.get("ingressSourceCidr")),
    )
    check("rds platformVpcId rendered", params.get("platformVpcId") == "vpc-test", str(params.get("platformVpcId")))
    check(
        "rds platformSubnetIds rendered",
        params.get("platformSubnetIds") == ["subnet-aaaa", "subnet-bbbb"],
        str(params.get("platformSubnetIds")),
    )
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

# 8. env-injection naming + patch builder + kustomize patches insert.
check("env_name camelCase", m._env_name("order-events", "queueUrl") == "MAKEWAY_ORDER_EVENTS_QUEUE_URL")
check("env_name snake IAM", m._env_name("storage", "aws_access_key_id") == "MAKEWAY_STORAGE_AWS_ACCESS_KEY_ID")
check("env_name plain key", m._env_name("db", "password") == "MAKEWAY_DB_PASSWORD")
check("env_name arn", m._env_name("storage", "bucketName") == "MAKEWAY_STORAGE_BUCKET_NAME")

patch = m._inject_env_patch("storage", ["orders-api"], ["bucketName", "region", "aws_access_key_id"])
check("inject patch has kind/name",
      "kind: Deployment" in patch and "metadata:" in patch and "name: orders-api" in patch)
check("inject patch valueFrom secretKeyRef name=slug",
      "name: storage" in patch and "secretKeyRef:" in patch)
check("inject patch env names",
      "MAKEWAY_STORAGE_BUCKET_NAME" in patch and "MAKEWAY_STORAGE_REGION" in patch
      and "MAKEWAY_STORAGE_AWS_ACCESS_KEY_ID" in patch)
check("inject patch key refs",
      "key: bucketName" in patch and "key: aws_access_key_id" in patch)

patch = m._add_kustomization_patch(
    "resources:\n  - namespace.yaml\npatches:\n  - path: orders-api-patch.yaml\n",
    "inject/storage-env.yaml",
)
check("kustomize patches insert",
      "  - path: inject/storage-env.yaml\n  - path: orders-api-patch.yaml" in patch)
check("kustomize patches idempotent",
      m._add_kustomization_patch(patch, "inject/storage-env.yaml") == patch)

# 9. State-machine skip contracts. Each SFN Task's output becomes the next
#    state's entire input, so the apply-skip return must carry the keys the
#    "Step2 Check" payload references ($.request_id / $.job_id / $.attempt).
#    Stub the control-plane call (and STS for _check) — no network.
m._control_plane = lambda method, path, payload=None: {
    "job": {"status": "success"},
    "app": {"appName": "order-service"},
    "capabilities": [],
}
m._account_id = lambda: "123456789012"
skip = m._apply(1, 1, None, {})
check("apply skip keys", set(skip) == {"status", "reason", "request_id", "job_id", "attempt"}, str(skip))
check("apply skip attempt == 1", skip.get("attempt") == 1)

# 10. check's return contract — "Step2 Ready?" reads $.ready, "Step2 Attempt?"
#     reads $.attempt, and Step2 Retry does States.MathAdd($.attempt, 1).
chk = m._check(7, 9, None, {"attempt": 3})
check("check keys", set(chk) == {"ready", "pending", "attempt", "request_id", "job_id"}, str(chk))
check("check ready + attempt passthrough", chk["ready"] is True and chk["attempt"] == 3)

# 11. _gone — teardown readiness: only a 404 means the object is gone; any
#     other status (a live object, a transient API error) keeps it pending.
check("gone: 404 is gone", m._gone(404) is True)
check("gone: 200 still exists", m._gone(200) is False)
check("gone: 409 conflict not gone", m._gone(409) is False)
check("gone: 500 server error not gone", m._gone(500) is False)

# 12. _removed_capability_keys — the (env, capabilityType) teardown set each
#     request type produces (mirrors control-plane rawRequest shapes).
#    delete_app: every capability in the target env, and only those.
delete_details = {
    "requestType": "delete_app",
    "rawRequest": {"app_name": "order-service", "env": "qa"},
    "capabilities": [
        {"capabilityType": "rel_database", "environment": "qa"},
        {"capabilityType": "storage", "environment": "qa"},
        {"capabilityType": "rel_database", "environment": "uat"},
    ],
}
removed = m._removed_capability_keys(delete_details)
check(
    "delete_app removes only target-env caps",
    removed == {("qa", "rel_database"), ("qa", "storage")},
    str(removed),
)
check(
    "delete_app without env -> empty",
    m._removed_capability_keys({
        "requestType": "delete_app",
        "rawRequest": {"app_name": "order-service"},
        "capabilities": delete_details["capabilities"],
    }) == set(),
)
#    update_app: pairs from the entries' remove_capabilities lists.
update_details = {
    "requestType": "update_app",
    "rawRequest": {
        "app_name": "order-service",
        "updates": [
            {"env": "qa", "remove_capabilities": ["rel_database"]},
            {"env": "prod", "remove_capabilities": ["storage", "messaging"]},
            {"env": "uat"},
        ],
    },
}
removed = m._removed_capability_keys(update_details)
check(
    "update_app pairs per entry",
    removed == {("qa", "rel_database"), ("prod", "storage"), ("prod", "messaging")},
    str(removed),
)
check(
    "create_app -> empty",
    m._removed_capability_keys({"requestType": "create_app", "rawRequest": {}}) == set(),
)
check(
    "update without removals -> empty",
    m._removed_capability_keys({
        "requestType": "update_app",
        "rawRequest": {"updates": [{"env": "qa", "capabilities": [{"type": "storage"}]}]},
    }) == set(),
)

# 13. Mixed-mode partition — the kept/removed split _apply/_check/_extract use.
#     A capability whose (environment, type) is in the removal set tears down
#     even in an update that also upserts others; the same type in a different
#     env stays kept.
part_caps = [
    {"capabilityType": "rel_database", "environment": "qa", "config": {"name": "orders"},
     "namespace": "order-service-qa", "capabilityId": "cap-db-qa"},
    {"capabilityType": "storage", "environment": "qa", "config": {"s3": {}},
     "namespace": "order-service-qa", "capabilityId": "cap-st-qa"},
    {"capabilityType": "rel_database", "environment": "prod", "config": {"name": "orders"},
     "namespace": "order-service-prod", "capabilityId": "cap-db-prod"},
]
u_removed = m._removed_capability_keys({
    "requestType": "update_app",
    "rawRequest": {"updates": [{"env": "qa", "remove_capabilities": ["rel_database"]}]},
})
kept, dropped = [], []
for cap in part_caps:
    (dropped if m._capability_is_removed(cap, u_removed) else kept).append(cap["capabilityId"])
check("mixed partition: removed cap isolated", dropped == ["cap-db-qa"], str(dropped))
check(
    "mixed partition: kept caps untouched (other env + other type)",
    kept == ["cap-st-qa", "cap-db-prod"],
    str(kept),
)

# 14. _claim_iam_user — the IAM identity extract created and teardown removes
#     (same name, so per-claim cleanup hits exactly the right user).
iam_claim = m._claims_for("order-service", part_caps[0], "123456789012")[0]
check(
    "iam user name deterministic",
    m._claim_iam_user(iam_claim) == "makeway-order-service-qa-orders",
    m._claim_iam_user(iam_claim),
)

print()
if fails:
    sys.exit("FAILED: " + ", ".join(fails))
print("step2 handler smoke: ALL PASS")