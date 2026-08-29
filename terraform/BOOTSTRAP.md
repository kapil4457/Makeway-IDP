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
The trust policy uses GitHub's **immutable OIDC subject claim** (`OWNER@OWNER-ID/REPO@REPO-ID`) — required for repos created/renamed after 2026-07-15. The IDs are **required** vars in the bootstrap root, kept out of git.

Find the IDs via the GitHub API:
```sh
curl -s https://api.github.com/repos/<owner>/<repo>   # .owner.id -> github_owner_id
                                                      # .id       -> github_repo_id
```
Create `terraform/bootstrap/terraform.tfvars` (gitignored):
```sh
cd terraform/bootstrap
cat > terraform.tfvars <<'EOF'
github_owner_id = "<owner-id>"
github_repo_id  = "<repo-id>"
EOF
```

### 3a. Bootstrap — GitHub Actions OIDC identity (own root + own state)
The provider + role live in `terraform/bootstrap/` with state key
`bootstrap/terraform.tfstate`. A platform `terraform destroy` never touches
this state, so CI can always redeploy after a teardown.
```sh
cd terraform/bootstrap
terraform init -input=false
terraform validate -no-color
terraform plan -input=false -no-color
terraform apply -input=false -auto-approve -no-color
```
Creates: GitHub OIDC provider, IAM role `github-actions-terraform` (no other
resources — explicitly NOT the platform infra).

Record the role ARN (needed in step 5):
```sh
terraform output github_actions_role_arn
```

Verify the live trust policy (should list both `ref:` and `environment:` subjects):
```sh
aws iam get-role --role-name github-actions-terraform \
  --query 'Role.AssumeRolePolicyDocument'
```

### 3b. Platform infra (own root + own state)
```sh
cd terraform
terraform init -input=false
terraform validate -no-color
terraform plan -input=false -no-color   # preview what will be created
terraform apply -input=false -auto-approve -no-color   # create the platform
```
Creates: SQS `makeway-requests` + DLQ, VPC, ALB, RDS, ECS, bastion.
The OIDC identity is already provisioned by 3a — the platform root does not
re-create it.

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
| `AWS_ROLE_ARN` | from `cd terraform/bootstrap && terraform output github_actions_role_arn` |

**Variables** (prefix can't be `GITHUB_` — reserved by GitHub):
| Name | Value |
|---|---|
| `OIDC_GITHUB_OWNER_ID` | `<github_owner_id>` (from step 2) |
| `OIDC_GITHUB_REPO_ID` | `<github_repo_id>` (from step 2) |
| `AWS_REGION` | `ap-south-1` |

`OIDC_GITHUB_OWNER_ID` / `OIDC_GITHUB_REPO_ID` are still set here for record, but the `deploy-infra` / `destroy-infra` / `deploy-control-plane` workflows no longer inject them as `TF_VAR_*` — the platform root no longer declares the `github_*` variables. Only `AWS_REGION` is used by the workflows (as `vars.AWS_REGION`).

## After bootstrap
- CI deploy workflow assumes the role via OIDC. No AWS keys in GitHub.
- Infra changes are applied by the workflow (`makeway-infra-deploy` env = manual approval gate).
- The apply job runs in an `environment`, so the OIDC subject is `environment:makeway-infra-deploy` (not `ref:`) — the trust policy must allow both, which it now does.
- The OIDC identity has **its own Terraform state** (`bootstrap/terraform.tfstate`). A platform destroy (`terraform destroy` in `terraform/`) never removes it, so CI can always redeploy.

## Useful ops commands
```sh
# verify OIDC provider + role exist
aws iam list-open-id-connect-providers
aws iam get-role --role-name github-actions-terraform --query 'Role.Arn'

# OIDC identity lives in its own root/state — manage it separately:
cd terraform/bootstrap
terraform init     # first time
terraform plan     # e.g. to rotate the role, add a policy
terraform apply

# NEVER destroy this with the platform. If you truly want to remove the OIDC
# identity too, run `terraform destroy` here AFTER tearing down the platform.

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
