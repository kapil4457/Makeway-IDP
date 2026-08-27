# Terraform Bootstrap (first-time only)

Bootstrap the platform infra from an empty AWS account. Everything after step 3 runs via GitHub Actions (OIDC — no static keys).

## Prerequisites
- AWS CLI authenticated (SSO/root session)
- Terraform installed (`~> 1.15`)

## Steps

1. **Create the state bucket** (Terraform cannot create its own backend)
   ```sh
   aws s3api create-bucket --bucket makeway-terraform-state --region ap-south-1 \
     --create-bucket-configuration LocationConstraint=ap-south-1
   aws s3api put-bucket-versioning --bucket makeway-terraform-state \
     --versioning-configuration Status=Enabled
   ```

2. **Init & apply**
   ```sh
   cd terraform
   terraform init
   terraform apply -auto-approve
   ```
   Creates: GitHub OIDC provider, IAM role `github-actions-terraform`, SQS `makeway-requests` + DLQ.

3. **Set the GitHub secret** (browser — GitHub requires your auth)
   `AWS_ROLE_ARN` = output value of `github_actions_role_arn` (or `arn:aws:iam::<acct>:role/github-actions-terraform`) under repo **Settings → Secrets and variables → Actions**.

## After bootstrap
- CI deploy workflow assumes the role via OIDC. No AWS keys in GitHub.
- Infra changes are applied by the workflow (`makeway-infra-deploy` env = manual approval gate).

## Notes
- Credentials via `~/.aws/credentials` expire — for one-off local runs after bootstrap, export `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` from the live session:
  ```sh
  export AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id)
  ```