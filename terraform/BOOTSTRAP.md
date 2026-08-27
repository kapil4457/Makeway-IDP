# Terraform Bootstrap (first-time only)

Bootstrap the platform infra from an empty AWS account. Everything after step 5 runs via GitHub Actions (OIDC — no static keys).

## Prerequisites
- AWS CLI authenticated (SSO/root session) — verify: `aws sts get-caller-identity`
- Terraform installed (`~> 1.15`) — verify: `terraform version`
- Git remote points at the repo: `git remote -v`

## Steps

### 1. Create the state bucket
Terraform cannot create its own backend, so the S3 bucket must exist before `terraform init`.
```sh
aws s3api create-bucket --bucket makeway-terraform-state --region ap-south-1 \
  --create-bucket-configuration LocationConstraint=ap-south-1
aws s3api put-bucket-versioning --bucket makeway-terraform-state \
  --versioning-configuration Status=Enabled
```

### 2. Provide the OIDC owner/repo IDs
The trust policy uses GitHub's **immutable OIDC subject claim** (`OWNER@OWNER-ID/REPO@REPO-ID`) — required for repos created/renamed after 2026-07-15. The IDs are **required** vars, kept out of git.

Find the IDs via the GitHub API:
```sh
curl -s https://api.github.com/repos/<owner>/<repo>   # .owner.id -> github_owner_id
                                                      # .id       -> github_repo_id
```
Create `terraform/terraform.tfvars` (gitignored; copy from `terraform.tfvars.example`):
```sh
cd terraform
cp terraform.tfvars.example terraform.tfvars
# edit: set github_owner_id and github_repo_id
```

### 3. Init, validate, plan, apply
```sh
cd terraform
terraform init -input=false        # configure S3 backend, download providers
terraform validate -no-color       # syntax + static checks
terraform plan -input=false -no-color   # preview what will be created
terraform apply -input=false -auto-approve -no-color   # create the infra
```
Creates: GitHub OIDC provider, IAM role `github-actions-terraform`, SQS `makeway-requests` + DLQ.

Verify the live trust policy (should list both `ref:` and `environment:` subjects):
```sh
aws iam get-role --role-name github-actions-terraform \
  --query 'Role.AssumeRolePolicyDocument'
```

### 4. Set up the local AWS credential bootstrap (one-off)
The SSO `login_session` token is short-lived (~1 min per cache write) and expires mid-apply. To give Terraform a working credential, refresh the session, write the live token to `~/.aws/credentials`, apply, then remove it:
```sh
aws sts get-caller-identity >/dev/null 2>&1   # refresh the session
python - <<'PY'
import json
d=json.load(open(r"~/.aws/login/cache/<cache>.json", encoding="utf-8"))["accessToken"]
with open(r"~/.aws/credentials","w",encoding="utf-8") as fh:
    fh.write("[default]\n")
    fh.write(f"aws_access_key_id = {d['accessKeyId']}\n")
    fh.write(f"aws_secret_access_key = {d['secretAccessKey']}\n")
    fh.write(f"aws_session_token = {d['sessionToken']}\n")
PY
# run terraform apply (see step 3) within the fresh token window
rm -f ~/.aws/credentials          # remove the temp file when done
```
> Note: `~/.aws/login/cache/<cache>.json` is the single JSON file in that folder. Read `accessToken.expiresAt` to check remaining life:
> ```sh
> python -c "import json,datetime;d=json.load(open('<cache>',encoding='utf-8'));print(d['accessToken']['expiresAt'])"
> ```

If an apply crashes mid-run and leaves a stale S3 lock, force-unlock it:
```sh
terraform force-unlock -force <LOCK_ID>
```
Get the lock ID from the apply error, or list state locks via the S3 object's metadata: `aws s3api get-object-attributes --bucket makeway-terraform-state --key platform/terraform.tfstate`.

### 5. Set the GitHub secret + variables (browser)
GitHub requires your auth to write these — set under repo **Settings → Secrets and variables → Actions**, for the repo `kapil4457/Makeway-IDP`:

**Secret:**
| Name | Value |
|---|---|
| `AWS_ROLE_ARN` | `arn:aws:iam::<acct>:role/github-actions-terraform` (from `terraform output github_actions_role_arn`) |

**Variables** (prefix can't be `GITHUB_` — reserved by GitHub):
| Name | Value |
|---|---|
| `OIDC_GITHUB_OWNER_ID` | `<github_owner_id>` (from step 2) |
| `OIDC_GITHUB_REPO_ID` | `<github_repo_id>` (from step 2) |
| `AWS_REGION` | `ap-south-1` |

These feed the `deploy-infra` workflow: `TF_VAR_github_owner_id` / `TF_VAR_github_repo_id` are injected from the `OIDC_*` variables so plan/apply resolve the required vars on the runner.

## After bootstrap
- CI deploy workflow assumes the role via OIDC. No AWS keys in GitHub.
- Infra changes are applied by the workflow (`makeway-infra-deploy` env = manual approval gate).
- The apply job runs in an `environment`, so the OIDC subject is `environment:makeway-infra-deploy` (not `ref:`) — the trust policy must allow both, which it now does.

## Useful ops commands
```sh
# verify OIDC provider + role exist
aws iam list-open-id-connect-providers
aws iam get-role --role-name github-actions-terraform --query 'Role.Arn'

# check SQS + DLQ
aws sqs get-queue-url --queue-name makeway-requests
aws sqs list-queues --region ap-south-1

# troubleshoot the role assumption from CI
#   "Not authorized to perform sts:AssumeRoleWithWebIdentity"
#   -> compare the OIDC subject your workflow actually sends vs the trust policy.
#   plan (no env)      : ...:ref:refs/heads/main
#   apply (env)        : ...:environment:makeway-infra-deploy
```

## Troubleshooting
- **`No value for required variable` (github_owner_id / github_repo_id)** — the `OIDC_*` repo variables aren't set, or the runner can't see `terraform.tfvars` (it's gitignored). Set the two repo variables (step 5).
- **`Not authorized to perform sts:AssumeRoleWithWebIdentity`** — OIDC subject mismatch. Most common: the job runs in an `environment` but the trust policy only allows `ref:`. Ensure both subjects are in the policy (they are now).
- **`invalid tag ":latest"` (Docker build)** — the `DOCKERHUB_IMAGE` variable is empty; see the README CI/CD section.
- **Stale state lock** — `terraform force-unlock -force <LOCK_ID>` (only if you're certain no other run is in progress).
