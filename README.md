# Makeway

Self-service internal developer platform. A developer requests an app with a set of capabilities (database, cache, queue, storage, CDN). Makeway creates the GitHub repo, provisions the infrastructure, sets up access control, and deploys the app through GitOps.

## CI/CD Setup

Infrastructure is provisioned via Terraform and deployed via GitHub Actions using OIDC (no static AWS keys).

1. **Bootstrap once** — see [terraform/BOOTSTRAP.md](terraform/BOOTSTRAP.md) (create state bucket, `terraform init` + `apply`).
2. **Set GitHub Actions secret** (repo **Settings → Secrets and variables → Actions**):
   - `AWS_ROLE_ARN` = `arn:aws:iam::<ID>:role/github-actions-terraform` (from Terraform output `github_actions_role_arn`)
   - optional `AWS_REGION` variable defaults to `ap-south-1`
3. `deploy-infra` workflow assumes the role via OIDC; `makeway-infra-deploy` environment is the manual approval gate before apply.

Optional (Docker image build/push): secrets `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, var `DOCKERHUB_IMAGE`.

## Flow

1. Developer submits a request via CLI or API.
2. Client generates an idempotency key once, reused on retries.
3. Request and capability rows written to Postgres as `PENDING`.
4. Request triggers AWS Step Functions.
5. Step Functions runs the state machine: create repo, create namespace, provision infra, set up access, register with ArgoCD.
6. ArgoCD syncs the app to the target cluster.
7. Status updates flow back to Postgres at each step.

Schema: see `Database.md` in `docs > design`.

## Orchestration

AWS Step Functions runs the provisioning workflow as a state machine.

| Task | Compute |
|---|---|
| Create GitHub repo, push skeleton | Lambda |
| Create namespace, apply NetworkPolicy | Lambda |
| Provision database, cache, queue, storage, CDN | Fargate (`.sync` task, Terraform), parallel per capability |
| Create IAM roles, inject secrets | Lambda |
| Register ArgoCD app, wait for sync | Lambda |

Fargate runs `terraform apply` inside a pre-built image (Terraform + modules), pulled from ECR. Auth via IAM Task Role, no stored credentials. Task calls back to the control-plane API after apply; no direct DB write from inside the task.

## Compute

EKS worker nodes: EC2. Required for NetworkPolicy and DaemonSet support.

Step Functions infra provisioning: Fargate. Short, bursty, infrequent jobs; no idle cost.

## Idempotency

Client generates a UUID once per logical request, reused across retries of that request. Server enforces a unique constraint on `idempotencyKey`. Prevents duplicate infrastructure from network retries.

## Access Control

Three layers:

1. **IAM (IRSA):** Kubernetes ServiceAccount bound to a scoped IAM role per service.
2. **NetworkPolicy:** default-deny, explicit allow rules per namespace. Kubernetes default allows cross-namespace pod traffic without this.
3. **Security Groups:** RDS/ElastiCache scoped to the owning namespace's Security Group.

NetworkPolicy and IAM required from day one. Security Group per-namespace scoping deferred; single VPC-scoped Security Group used initially.

## Networking

Public subnets: ALB, NAT Gateway.
Private subnets: EKS worker nodes, one per AZ.

One ALB per cluster, provisioned by AWS Load Balancer Controller via Ingress resources.

No API Gateway. Control-plane API reached directly (Lambda Function URL or ALB).

`Service.exposureType`: `PUBLIC` or `NONE`. `PUBLIC` gets an Ingress. `NONE` is reachable only via internal Kubernetes Service DNS.

## ArgoCD

One ArgoCD instance per environment, on the same cluster it manages.

## GitOps Loop

```
Developer pushes code
  → CI builds image, pushes to ECR
  → CI updates image tag in deploy-manifests repo (Git commit)
  → ArgoCD detects the commit
  → ArgoCD syncs to the cluster
```

ArgoCD watches Git, not the registry.

## Orchestration Choice: Step Functions vs Temporal

Temporal gives durable execution, automatic retries, and no manual state tracking; used in production by Grab, Stripe, Netflix. Temporal Cloud starts at $200/month in support fees; self-hosting requires an always-on cluster.

Step Functions: pay-per-state-transition, fully managed, AWS-native. Chosen for this project on cost and operational grounds.

## Tech Stack

- **Control plane:** Python, FastAPI, PostgreSQL
- **Orchestration:** AWS Step Functions, Lambda, ECS Fargate
- **Infrastructure:** Terraform, AWS (EKS, RDS, ElastiCache, S3, SNS/SQS, CloudFront, IAM)
- **Delivery:** GitHub Actions, ArgoCD, Helm
- **Secrets:** AWS Secrets Manager
- **Networking:** AWS Load Balancer Controller, Kubernetes NetworkPolicy, Security Groups


## Database Migration
- Done via `alembic`.
- Initialization command : `alembic init migrations`
- Create a database migration : `alembic revision --autogenerate -m "<migration-description>"`
- Apply migration current state to database : `alembic upgrade head`
- See migration history : `alembic upgrade head`
- See latest migration :  `alembic heads`
- Upgrade by n migrations from the stack : `alembic upgrade +1` or `alembic upgrade +2` ....
- Upgrade to specific migration : `alembic upgrade <migration-hash>`
- Rollback by n migration from the stack : `alembic downgrade -1` or `alembic downgrade -2` ....
- Rollback to specific migration : `alembic downgrade <migration-hash>`
- Create an empty migration : `alembic revision -m "migrate cluster endpoints"`
- Review SQL before applying migration : `alembic upgrade head --sql`
- Generate SQL for a range of migration : `alembic upgrade base:head --sql`


## User creation scripts
 ```bash
cd app/control-plane
python -m scripts.create_user
 ```

 ## Connecting to RDS from local
 ```bash

- aws login --profile makeway
- export $(aws configure export-credentials --profile makeway --format env | tr -d '\r' | xargs)
- aws sts get-caller-identity
- winget install Amazon.SessionManagerPlugin
- export PATH="$PATH:/c/Program Files/Amazon/SessionManagerPlugin/bin"
- netstat -ano | grep 5432
- taskkill //F //PID 10072
- ./tunnel-rds.sh
```