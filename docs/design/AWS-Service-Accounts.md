# AWS Service Accounts — Reference Guide

Living guide for the AWS IAM service accounts, scoped policies, and local credentials used by the Makeway platform. As we add capabilities (SQS, Secrets Manager, DynamoDB, ECR, …), append the permission/account entries here with the same structure.

## Gitignore reference (what protects the secrets)

Rules from `.gitignore`:

| Rule | What it protects |
|---|---|
| `.env` | any `.env` at any level — service-account credentials live in the control plane's `app/control-plane/.env` |
| `.env.*` | derived variants (`.env.dev`, `.env.local`, …) |
| `!.env.example` | except the tracked skeleton, which has no real values |
| `*.tfvars` | live Terraform vars (e.g. `github_owner_id` / `github_repo_id` in `terraform/terraform.tfvars`) |
| `!*.tfvars.example` | except the tracked placeholder example |

Verify which file a path falls under:

```sh
git check-ignore -v app/control-plane/.env
```

## Service account registry

Each entry: account name, what it's for, the exact ARN(s) it may touch, and the actions granted. **Keep entries scoped to the narrowest set the platform needs today** — widen them only when a real need appears.

| Account | Purpose | Resource scope | Actions | Credentials in |
|---|---|---|---|---|
| `makeway-sa` | Control plane → SQS publish/consume (app-creation messages) | `arn:aws:sqs:<region>:<account-id>:makeway-requests` (+ DLQ) | `sqs:SendMessage`, `sqs:SendMessageBatch`, `sqs:GetQueueUrl`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility` | `app/control-plane/.env` |
| `makeway-crossplane` | Crossplane AWS provider on the cluster (compositions provision claims' resources) | Scoped RDS/S3/SQS/SNS build access + SecretsManager, exact ARNs per capability | RDS create/modify, S3 bucket + object, SQS queue, SNS topic | `crossplane/secrets/provider-creds.yaml` (bootstrap-only, gitignored content) |
| `makeway-{app}-{env}-{slug}` | **Per-claim** IAM users created by the Step-2 worker so pods on the local cluster (no IRSA) can call the AWS API — one user per S3/SQS/SNS claim | Exactly the resources that claim backs onto (bucket ARNs, queue+DLQ ARNs, topic ARN) | `s3:ListBucket/GetBucketLocation/GetObject/PutObject/DeleteObject`, `sqs:Send/Receive/Delete/ChangeMessageVisibility/GetQueueUrl/GetQueueAttributes`, `sns:Publish` | Step-2 `_ensure_aws_identity` — created automatically, keys mirrored into Secrets Manager |
| *(ESO store keys)* | ClusterSecretStore `makeway` → AWS Secrets Manager reads | `secretsmanager:GetSecretValue` on `makeway/*` prefix | `secretsmanager:GetSecretValue` | `external-secrets/aws-credentials` secret (bootstrap-only, gitignored content) |
| `github-actions-terraform` | GitHub Actions OIDC role (plan/apply/destroy of the platform root) | AssumeRole-like trust via GitHub OIDC; permissions come from attached policies | platform Terraform CRUD | Fed via OIDC (`AWS_ROLE_ARN` secret) — no static keys |
| *(GitHub PAT)* | All worker git/API calls (Step-1, Step-2, gitops commits) | GitHub REST + git-database API | `repo`, `workflow`, `read:user` | Secrets Manager `makeway/github-pat` (read at runtime, never baked into artifacts) |

> Rather than proliferate static pipelines, the platform steadily migrates
> machine identities to **IRSA / pod identity** once it lands on managed EKS:
> the Crossplane ProviderConfig, the ESO ClusterSecretStore, and the
> per-claim IAM users all collapse into role-differentiated service accounts.

## Registering credentials per environment

Service-account keys live in the gitignored `.env` of the consuming app (they override any `login_session` / SSO profile):

```env
AWS_ACCESS_KEY_ID=<access-key-id>
AWS_SECRET_ACCESS_KEY=<secret-access-key>
AWS_REGION=<region>
```

Restart the server after editing `.env` — it is read at startup and `--reload` only watches `.py` files.

## How to add a new service account

```sh
# 1. create the user
aws iam create-user --user-name <name>

# 2. attach a scoped inline policy — Resource must name the exact ARN it may touch
aws iam put-user-policy \
  --user-name <name> \
  --policy-name <policy-name> \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["<service>:<Action>", "<service>:<Action>"],
      "Resource": "<exact-resource-arn>"
    }]
  }'

# 3. create the access key — the secret is shown only once
aws iam create-access-key --user-name <name>

# 4. append the account to the registry table above with its scope + actions
```

## How to add more permissions to an existing account

No new credential needed — policy changes apply immediately:

```sh
# edit the same inline policy (add actions / widen the exact ARN if the scope grows)
aws iam put-user-policy \
  --user-name <name> \
  --policy-name <policy-name> \
  --policy-document '<updated-document>'

# verify the account really uses what it's granted before widening further
aws iam get-service-last-accessed-details --arn arn:aws:iam::<account-id>:user/<name>
```

Also update the registry entry above so the doc stays the single source of truth.

## Least-privilege rules of thumb

- Grant **specific actions, never `*`** where a concrete action exists.
- Scope **`Resource` to the exact ARN** (account ID + service + name), not `*`.
- Prefer **separate accounts per concern** (producer vs consumer vs CI) over one broad account.
- At ~3+ accounts, **use an IAM group** — manage permissions once on the group, members inherit.
- No `Principal: "*"` **queue/resource policies** — same-account access is covered by the caller's IAM policy.

## Verification (send a probe)

```sh
cd app/control-plane
.venv/Scripts/python - <<'PY'
import os, boto3
from dotenv import load_dotenv
load_dotenv(r"<abs-path>/app/control-plane/.env")
aid = os.environ.get("AWS_ACCESS_KEY_ID")
assert aid, "AWS_ACCESS_KEY_ID missing from .env"
c = boto3.client("sqs", region_name="<region>")
url = c.get_queue_url(QueueName="makeway-requests")["QueueUrl"]
print("authenticated OK ->", url)
r = c.send_message(QueueUrl=url, MessageBody='{"probe":true}')
print("send_message OK -> MessageId", r["MessageId"])
PY
```

Clean up the probe (makeway-sa can receive/delete on the queue):

```sh
.venv/Scripts/python - <<'PY'
import os, boto3
from dotenv import load_dotenv
load_dotenv(r"<abs-path>/app/control-plane/.env")
c = boto3.client("sqs", region_name="<region>")
url = c.get_queue_url(QueueName="makeway-requests")["QueueUrl"]
r = c.receive_message(QueueUrl=url, MaxNumberOfMessages=10)
n = 0
for m in r.get("Messages", []):
    c.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
    n += 1
print(f"deleted {n} message(s)")
PY
```

## Troubleshooting

- **`AccessDenied`** (e.g. `sqs:getqueueattributes`) — least privilege working as intended. Add the action to the inline policy only if the app genuinely needs it.
- **500 + `CreateOAuth2Token … invalid, expired, revoked, or malformed`** — the app is still on a short-lived `login_session` profile. Ensure `.env` has the service-account keys and the server was restarted after editing `.env`.
- **`MissingDependencyException … pip install "botocore[crt]"`** — botocore's `login` credential provider needs `awscrt`; `botocore[crt]` is pinned in `requirements.txt`.
- **`.env` edits not taking effect** — uvicorn `--reload` ignores `.env`; restart the server.