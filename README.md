# Makeway

An **AI-assisted internal developer platform**. A developer asks for an app — the language stacks, a database, storage, a message queue, a notification topic — and Makeway does the rest: it creates the GitHub monorepo, scaffolds the services, provisions the real AWS infrastructure through Crossplane, and rolls the app out to Kubernetes through GitOps. Boring, repeatable, and fully automated.

The platform's pitch is simple: **declared state is the truth, and reconciliation is the mechanism.** The control plane records what a team asked for, workers keep turning that into reality, and ArgoCD keeps reality matching what was asked.

---

## How it works at a glance

```mermaid
flowchart LR
    subgraph Developer
        D[Developer] -->|POST /app/create + idempotency key| API
    end

    subgraph ControlPlane["Control plane (FastAPI + PostgreSQL)"]
        API[app_router] --> SVC[AppCreationService]
        SVC -->|atomic write| DB[(Postgres)]
        SVC --> QUEUE[(SQS makeway-requests)]
    end

    subgraph Workers["App-creation workflow (Step Functions)"]
        CONSUMER[SQS consumer Lambda pool] -->|start_execution| SFN
        SFN --> S1[Step 1 · GitHub Setup]
        S1 --> S2[Step 2 · Apply XR instances]
        S2 --> WAIT[Wait]
        WAIT --> CHECK[Check Ready+Synced]
        CHECK -->|not ready| WAIT
        CHECK -->|ready| EXTRACT[Step 2 · Extract]
        S1 -.status callback.-> API
        EXTRACT -.per-capability outputs.-> API
    end

    subgraph GitHub
        REPO[&lt;appName&gt; services monorepo + CI] 
        GITOPS[argocd/apps/&lt;app&gt; in platform repo]
    end

    subgraph Cluster["Local Kubernetes cluster"]
        ARGO[ArgoCD] -->|syncs| CROSS[Crossplane]
        CROSS -->|Compositions| AWS[(AWS resources)]
        ESO[External Secrets Operator] -->|materializes| K8SSEC[K8s Secrets]
    end

    S1 --> REPO
    S1 --> GITOPS
    EXTRACT --> GITOPS
    EXTRACT --> SM[(AWS Secrets Manager)]
    GITOPS --> ARGO
    SM --> ESO
    K8SSEC --> APP[Generated app running on cluster]
```

Three moving parts cooperate:

1. **Control plane** — a FastAPI service that owns the catalog (teams, users, apps, services, capabilities) and the desired state. `POST /app/create` records everything in one atomic Postgres transaction, then drops a message on SQS.
2. **App-creation workflow** — an AWS Step Functions state machine, fed by a Lambda pool that watches SQS. Step 1 scaffolds the code and GitOps; Step 2 provisions infrastructure through Crossplane XR instances and delivers credentials back.
3. **The cluster** — a Kubernetes cluster (running locally today) with ArgoCD, Crossplane, and External Secrets Operator. It continually reconciles the GitOps folder and the Crossplane XR instances into live resources and secrets.

---

## The full request lifecycle

Walking through what happens when a developer creates an app:

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant CP as Control plane
    participant SQS as SQS queue
    participant SFN as Step Functions
    participant S1 as Step-1 Lambda (GitHub Setup)
    participant S2 as Step-2 Lambda (Crossplane)
    participant GH as GitHub
    participant Argo as ArgoCD
    participant XP as Crossplane
    participant ESO as External Secrets
    participant AWS as AWS account

    Dev->>CP: POST /app/create (app_config, Idempotency-Key)
    CP->>CP: validate team + env constraints
    CP->>CP: App + Services + Capabilities + InfraRequirements + Request + Job (atomic)
    CP->>SQS: publish {request_id, job_id}
    CP-->>Dev: 202 {request_id, job_id, status}

    SQS->>SFN: consumer Lambda pool → start_execution (dedup name)
    SFN->>S1: invoke (request_id, job_id)
    S1->>CP: GET /internal/requests/{id} (desired state)
    S1->>GH: create {app} monorepo + scaffold golden-path services + CI
    S1->>GH: PR argocd/apps/{app} (base/apps/envs) → auto-merge
    S1->>CP: POST status success + repo URLs + service paths

    SFN->>S2: invoke action=apply
    S2->>CP: GET /internal/requests/{id} (with capabilities)
    S2->>XP: upsert XR instances into {app}-{env} namespaces
    S2->>S2: generate RDS master password Secret
    SFN->>SFN: Wait → Check (Ready+Synced?) → loop up to 30×
    XP->>AWS: provision RDS / S3 / SQS+DLQ / SNS via Compositions
    XP->>S2: connection Secret {xr}-connection-details

    SFN->>S2: invoke action=extract
    S2->>S2: mirror creds → Secrets Manager (merge, idempotent)
    S2->>AWS: create scoped IAM user + keys (AWS-API caps)
    S2->>GH: commit ExternalSecret into gitops env overlay
    Argo->>ESO: sees ExternalSecret → fetches from Secrets Manager
    ESO->>AWS: GetSecretValue
    ESO-->>Argo: materialize K8s Secret into app namespace
    S2->>CP: POST per-capability {status, outputRef, secretRef}
    CP->>CP: roll up request status and persist outputs
```

### Idempotency is built in, not bolted on

- **The client** sends a UUID `Idempotency-Key` header; the control plane returns the original `requestId`/`jobId` for a repeated key instead of re-registering.
- **The queue consumer** uses a deterministic execution name (`app-creation-{request_id}-{job_id}`), so at-least-once SQS delivery can never start two overlapping executions.
- **Step 1** checks repo existence and diffs against the current git tree before pushing — re-runs are no-ops.
- **Step 2** uses deterministic XR instance names with upsert (POST on 404, merge-patch otherwise), create-or-reuse IAM, and a merge-onto-existing Secrets Manager secret so a retry never drops credentials AWS returned only once.

---

## Repository layout

```
Makeway/
├── app/
│   └── control-plane/          FastAPI control plane (the catalog + desired state)
│       ├── controllers/        Route handlers (app, auth, cluster, internal, swagger)
│       ├── dto/                Request/response schemas, config DTOs, enums
│       ├── service/            Business logic (app creation, internal API, auth…)
│       ├── repository/         Data access (thin, session-scoped)
│       ├── database/models/    SQLAlchemy/SQLModel tables
│       ├── migrations/         Alembic revisions
│       ├── scripts/            Operational CLIs (users, teams, members)
│       └── tests/              Internal-API service tests (python tests/…)
│
├── workers/
│   ├── sqs_consumer/           Lambda pool → fans SQS messages into the state machine
│   └── step_functions/
│       ├── step_1 - GitHub Setup/       Scaffold repo + GitOps (templates/, ci_templates/)
│       └── step_2 - Infra Provisioning/ Crossplane claims + extract (claim_templates/)
│
├── argocd/
│   ├── root-application.yaml   ApplicationSet: argocd/apps/*/envs/* → per-env Applications
│   └── external-secrets/       ESO bootstrap: ClusterSecretStore + install/store Applications
│
├── crossplane/
│   ├── providers/              Provider packages (aws family + services)
│   ├── secrets/                Bootstrap-only provider credentials (NOT ArgoCD-managed)
│   └── compositions/           XRD + Composition per capability (storage, database,
│                               queue, notification)
│
├── terraform/
│   ├── bootstrap/              GitHub Actions OIDC identity (own root + own state)
│   ├── modules/                Reusable AWS modules (vpc, eks, sqs, rds, ecs, alb…
│   │                           and app_creation_step_functions/sqs_consumer)
│   └── main.tf                 The platform root (VPC, SQS, ECS, ALB, RDS, bastion,
│                               worker Lambdas + state machine)
│
├── docs/
│   ├── design/                 Database, deployment model, AWS service accounts
│   └── diagrams/               Flow diagrams (drawio / svg)
└── .github/workflows/          OIDC Terraform pipeline + control-plane CI/CD
```

---

## The two worker steps

The state machine (`makeway-app-creation`) runs one Lambda in three different roles.

### Step 1 — GitHub Setup (`workers/step_functions/step_1 - GitHub Setup/handler.py`)

Creates the app's **services monorepo** (`<appName>` under the configured GitHub owner):

- One golden-path folder per service, deduplicated by base name — `orders-api-qa` and `orders-api-uat` share a single `orders-api` folder.
- A per-service CI workflow (`.github/workflows/ci-<service>.yaml`) that builds on merge to the branch promoting each tier: `feature/* → qa`, `release/* → uat`, `main → prod`.

Then publishes the app's **GitOps configuration into the Makeway platform repo itself** — no per-app gitops repo. `argocd/apps/<appName>/` gets the base/apps/envs kustomize layout, landed through a feature-branch PR that auto-merges when branch protection allows it (and stays open for review otherwise).

### Step 2 — Crossplane Provisioning (`workers/step_functions/step_2 - Infra Provisioning/handler.py`)

The same Lambda, invoked three times with an `action`:

| action | what it does |
|---|---|
| `apply` | Renders one or more Crossplane **XR instances** (namespaced composite resources) per capability and upserts them into the `{appName}-{env}` namespace. Generates the RDS master password Secret the composition references. |
| `check` | Polls each XR instance's `status.conditions` for `Ready` + `Synced`. The state machine loops (`Wait → Check → Choice`) up to `step2_max_attempts` times. |
| `extract` | Reads each XR instance's connection Secret, mirrors the credentials into **AWS Secrets Manager** (merging onto existing values), provisions a scoped **IAM user + access keys** for AWS-API capabilities (S3/SQS/SNS pods have no IRSA on the local cluster), then commits an **ExternalSecret** into the gitops env overlay so ESO materializes the K8s Secret the app actually consumes. |

Both workers report back to the control plane through the internal API — status, app repo URLs, per-service folder paths, and per-capability `outputRef`/`secretRef`.

### Capability → Composition map

| CapabilityType | XRD (XR kind) | Provisioned by Crossplane | Connection keys |
|---|---|---|---|
| `rel_database` | `RelationalDatabase` | RDS + subnet group + security group (TCP 5432) | endpoint, port, databaseName, username, password |
| `storage` | `ObjectStorage` | S3 bucket (+ CloudFront when requested) | bucketName, region |
| `messaging` (queue) | `MessageQueue` | SQS queue + DLQ | queueUrl, queueArn, dlqUrl, dlqArn |
| `messaging` (notification) | `NotificationTopic` | SNS topic | topicArn |

---

## The GitOps loop (how apps get deployed)

```mermaid
flowchart LR
    B[merge promoting branch<br/>feature/* → qa · release/* → uat · main → prod] --> CI
    CI[service CI builds image, pushes to registry] -->|commits image tag bump| P[env overlay patch<br/>argocd/apps/&lt;app&gt;/envs/&lt;env&gt;/]
    P --> ARGO[ArgoCD detects commit]
    ARGO -->|sync| CLUSTER[(cluster)]
```

ArgoCD watches Git, not the registry. Every deploy provably maps to a build — the git history records the exact image SHA that went live. A rollback is a `git revert` on the bump commit.

GitOps configs live in the **platform repo** (`argocd/apps/<app>/`), not per-app repos, because the `makeway-apps` ApplicationSet's git generator discovers `argocd/apps/*/envs/*` — a new app is simply a directory the Step-1 worker creates. No wiring, no per-app repo, no per-app secret.

### Secrets have a delivery path of their own

```mermaid
flowchart LR
    XP[Crossplane XR connection Secret] --> S2[Step-2 extract]
    S2 --> SM[(AWS Secrets Manager)]
    S2 --> G[gitops env overlay<br/>external-secrets/…]
    G --> ARGO[ArgoCD] --> ESO[External Secrets Operator]
    SM --> ESO
    ESO --> KS[K8s Secret in app namespace]
    KS --> DEP[Deployment envFrom]
```

The app-facing `ExternalSecret` + `envFrom` wiring is byte-identical between today's local cluster and a future managed EKS — only the secret store's **auth** changes (static keys → IRSA), exactly like the Crossplane ProviderConfig.

---

## Security model

- **Deepest credentials are bootstrap-only, out of git.** The Crossplane provider keys, the ESO store keys, and access-control are applied by hand once and deliberately excluded from the kustomization roots — ArgoCD's `selfHeal`/`prune` would otherwise "repair" live credentials back to placeholders on every sync.
- **No cluster credentials in app CI.** The GitOps repo is the only write path into the cluster; a workflow in a service repo can commit YAML, it can never `kubectl`.
- **Least privilege everywhere.** The control plane's task role can only touch its SQS queue; the Step-2 Lambda gets per-XR-instance IAM users scoped to exactly the resources that capability backs onto; the GitHub PAT is read at runtime from Secrets Manager, never baked into artifacts.
- **The internal API is fail-closed.** Worker endpoints are guarded by an `X-Internal-API-Key` shared secret (auto-generated and injected by Terraform).

See [docs/design/AWS-Service-Accounts.md](docs/design/AWS-Service-Accounts.md) for the full service-account registry.

---

## How the platform itself is deployed

The platform's own infrastructure is Terraform, applied through GitHub Actions with **OIDC federation** (no static keys in GitHub):

- **`terraform/bootstrap/`** creates the GitHub OIDC provider and the `github-actions-terraform` role — in its own Terraform root with its own state, so a platform teardown can never take CI down with it.
- **`terraform/`** is the platform root — VPC, SQS (`makeway-requests`), ALB, ECS-hosted control plane, RDS, a bastion for database access, plus the worker Lambdas and the state machine itself. State lives in `makeway-terraform-state`.
- The `deploy-infra` workflow runs `plan` and `apply` behind the `makeway-infra-deploy` environment (a human approval gate on GitHub), executing the *exact same plan artifact* that was reviewed.

This is deliberate: a Terraform plan has to be seen by a human before it touches the VPC. It's the push half of the platform's two-sided deployment model — read [docs/design/Deployment-Model.md](docs/design/Deployment-Model.md) for the full argument.

---

## Tech stack

| Layer | Choice |
|---|---|
| Control plane | Python · FastAPI · PostgreSQL (SQLModel/SQLAlchemy + Alembic) |
| Orchestration | AWS Step Functions · Lambda · SQS |
| Infrastructure | Terraform · AWS (VPC, EKS/EKS-ready, SQS, RDS, S3, SNS, IAM) |
| Provisioning | Crossplane v2 (XR instances + pipeline-mode compositions per capability) |
| Delivery | GitHub Actions (OIDC) · ArgoCD · GitOps (kustomize) |
| Secrets | AWS Secrets Manager · External Secrets Operator |
| Git | GitHub (services monorepo per app, gitops in the platform repo) |

---

## Getting started

### 1. Clusters and GitOps (one-time bootstrap)

The raw infrastructure is Terraform (`terraform/BOOTSTRAP.md` → `terraform/README.md`). The cluster-side platform components are applied once by hand, then ArgoCD keeps them live:

```bash
# Crossplane + providers (see crossplane/README.md)
helm upgrade --install crossplane --namespace crossplane-system \
  --create-namespace crossplane-stable/crossplane
kubectl apply -f crossplane/providers/aws.yaml
kubectl apply -f crossplane/secrets/provider-creds.yaml
kubectl apply -n argocd -f crossplane/root-application.yaml

# External Secrets Operator (see argocd/external-secrets/README.md)
kubectl apply -n argocd -f argocd/external-secrets/eso-install-application.yaml
kubectl apply -n external-secrets -f aws-credentials.yaml   # bootstrap creds, gitignored
kubectl apply -n argocd -f argocd/external-secrets/store-application.yaml

# The per-app ApplicationSet (once)
kubectl apply -n argocd -f argocd/root-application.yaml
```

### 2. Control plane

```bash
cd app/control-plane
uv run uvicorn main:app --reload      # DATABASE_URL from .env
```

Bootstrap a team and users with the operational scripts (see `app/control-plane/scripts/README.md`):

```bash
python -m scripts.create_team --team-name orders \
  --owner-email admin@example.com --members dev@example.com
```

### 3. Create an app

```bash
curl -X POST http://localhost:8000/app/create \
  -H "Authorization: Bearer <jwt>" \
  -H "Idempotency-Key: 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d" \
  -H "Content-Type: application/json" \
  -d '{
    "app_name": "order-service",
    "team_name": "orders",
    "env_config": [{
      "env": "qa",
      "services": [
        {"service_type": "fast-api", "service_name": "orders-api"},
        {"service_type": "node-js",  "service_name": "web"}
      ],
      "capabilities": [
        {"config": {"type": "rel_database", "name": "orders", "capacity": 5},
         "access_to": ["orders-api"]},
        {"config": {"type": "messaging", "notification": true,
                    "queue": [{"name": "orders-queue"}]},
         "access_to": ["orders-api", "web"]}
      ]
    }]
  }'
```

From there, everything else happens on its own: the state machine runs, ArgoCD syncs, Crossplane provisions, ESO materializes the secrets, and your services meet the cluster exactly once (when the image tag CI wrote for them rolls off ArgoCD's deck).

---

## Configuration reference

Where every knob, env var, and Terraform input lives — and, crucially, **where
you configure it**: a GitHub Actions variable vs secret, your local (gitignored)
`terraform.tfvars`, an ECS task env var, AWS Secrets Manager, or auto-generated
on apply.

How the plumbing works:

- `terraform/terraform.tfvars` is **`.gitignore`d** (`*.tfvars`) — GitHub Actions
  never sees it. CI supplies the required Terraform inputs through `TF_VAR_*`
  env vars wired into the workflows: `TF_VAR_control_plane_url`,
  `TF_VAR_kube_api_endpoint`, `TF_VAR_kube_token` (+ optional
  `TF_VAR_kube_ca_cert`) and `TF_VAR_ecs_image`.
- Any secret whose tfvars default is `""` is **auto-generated on `apply`** and
  stored in encrypted terraform state — you do not configure it anywhere.
- Everything else is either a GHA variable/secret or a local tfvars value — see
  the consolidated table below.

### Where each item is configured — the single source of truth

| Item | Kind | Where to configure | GitHub var/secret? |
|---|---|---|---|
| `AWS_ROLE_ARN` | secret | repo **Secrets** · Actions (or env-level on `makeway-infra-deploy`) | 🔒 **Secret** |
| `AWS_REGION` | var | repo **Variables** · Actions | Variable |
| `MAKEWAY_CONTROL_PLANE_URL` | var | repo **Variables** · Actions → `TF_VAR_control_plane_url` | Variable |
| `DOCKERHUB_CONTROL_PLANE_IMAGE` | var | repo **Variables** · Actions (default `kapil4457/makeway-control-plane`) | Variable |
| `kube_api_endpoint` | var | repo **Variables** · Actions → `TF_VAR_kube_api_endpoint` | Variable |
| `kube_token` | secret | repo **Secrets** · Actions → `TF_VAR_kube_token` | 🔒 **Secret** |
| `kube_ca_cert` | var | repo **Variables** · Actions → `TF_VAR_kube_ca_cert` (optional; empty disables TLS verification) | Variable |
| `github_pat` | secret | **AWS Secrets Manager** ⇒ `makeway/github-pat` (Step-1 reads it at runtime) — never a GHA secret | none (Secrets Manager) |
| `internal_api_key` | secret | **nothing** — auto-generated on apply (tfvars default `""`) | none (auto-gen) |
| `db_password` | secret | **nothing** — auto-generated on apply (tfvars default `""`) | none (auto-gen) |
| `app_secret_key` (→ ECS `JWT_SECRET_KEY`) | secret | **nothing** — auto-generated on apply (tfvars default `""`) | none (auto-gen) |
| `github_owner`, `makeway_platform_repo` | var | defaults in `terraform/variables.tf` or local tfvars | none (default) |
| `region`, `vpc_cidr`, subnets, `azs` | var | defaults or local tfvars | none (default) |
| `ecs_*`, `rds_*`, `alb_*`, `bastion_*`, `step2_*` | var | defaults or local tfvars | none (default) |
| Control-plane env: `DATABASE_URL`, `APP_CREATION_QUEUE_URL`, `SQS_REGION`, `INTERNAL_API_KEY`, `JWT_SECRET_KEY`, `LOG_LEVEL` | env | **ECS task env** — built by `terraform/main.tf` from `local.*` / module outputs | none (Terraform-built) |
| `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` | secret | **platform repo** Secrets (for `build-control-plane.yaml`) **and every generated app repo** Secrets (for `ci-<service>.yaml`) | 🔒 **Secret** (both repos) |
| `DOCKERHUB_IMAGE` | var | **generated app repo** Variables | Variable (in app repo) |
| `GITOPS_PAT` | secret | **generated app repo** Secrets (for the tag-bump to gitops) | 🔒 **Secret** (in app repo) |

### GitHub Actions: exactly what to set

**Repo level** (or on the `makeway-infra-deploy` environment for tighter scope):

| Name | Kind | Used by |
|---|---|---|
| `AWS_ROLE_ARN` | 🔒 Secret | `deploy-infra.yaml`, `destroy-infra.yaml`, `deploy-control-plane.yaml` — OIDC assume-role |
| `AWS_REGION` | Variable | the three workflows above (default `ap-south-1`) |
| `MAKEWAY_CONTROL_PLANE_URL` | Variable | the workflows above → `TF_VAR_control_plane_url` |
| `MAKEWAY_KUBE_API_ENDPOINT` | Variable | the workflows above → `TF_VAR_kube_api_endpoint` |
| `MAKEWAY_KUBE_TOKEN` | 🔒 Secret | the workflows above → `TF_VAR_kube_token` |
| `MAKEWAY_KUBE_CA_CERT` | Variable | the workflows above → `TF_VAR_kube_ca_cert` (optional, empty = TLS off) |
| `DOCKERHUB_CONTROL_PLANE_IMAGE` | Variable | `build-control-plane.yaml` + `deploy-control-plane.yaml` image tag (default `kapil4457/makeway-control-plane`) |
| `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` | 🔒 Secrets | `build-control-plane.yaml` docker login + push |

> Set `MAKEWAY_*` (except the DockerHub ones) at **repo level**, not just the
> `makeway-infra-deploy` environment — the *plan* job in `deploy-infra.yaml` runs
> **without** an environment and needs to read them too.

**Generated app repos** (per app — `ci-<service>.yaml`):

| Name | Kind | Used by |
|---|---|---|
| `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` | 🔒 Secrets | docker login + push in `ci-<service>.yaml` |
| `DOCKERHUB_IMAGE` | Variable | image tag (`<repo>:<service>-<sha>`) |
| `GITOPS_PAT` | 🔒 Secret | tag-bump commit to the platform repo's gitops overlay |

### The required TF_VARs coming from GitHub Actions

`terraform.tfvars` is gitignored, so CI supplies the three **required** inputs
(no tfvars default) from GitHub Actions instead — wired into `deploy-infra.yaml`,
`deploy-control-plane.yaml` and `destroy-infra.yaml` (both plan/apply steps,
plus a fail-fast guard that names the missing variable):

| TF_VAR | GHA source | Kind |
|---|---|---|
| `TF_VAR_control_plane_url` | `MAKEWAY_CONTROL_PLANE_URL` | Variable |
| `TF_VAR_kube_api_endpoint` | `MAKEWAY_KUBE_API_ENDPOINT` | Variable |
| `TF_VAR_kube_token` | `MAKEWAY_KUBE_TOKEN` | 🔒 Secret |
| `TF_VAR_kube_ca_cert` | `MAKEWAY_KUBE_CA_CERT` | Variable (optional, default empty) |
| `TF_VAR_ecs_image` | `DOCKERHUB_CONTROL_PLANE_IMAGE` + `inputs.image_tag` | Variable |

Set `MAKEWAY_*` at **repo level** so the environment-less *plan* job in
`deploy-infra.yaml` can read them. `MAKEWAY_KUBE_TOKEN` should hold the
`makeway-worker` ServiceAccount token, and `MAKEWAY_KUBE_API_ENDPOINT` the
pinggy TCP-tunnel endpoint (`https://<host>:<port>` in front of
`127.0.0.1:6443`) — see the
[Step-2 README](workers/step_functions/step_2 - Infra Provisioning/README.md).
Every other Terraform input keeps its tfvars default — local `terraform.tfvars`
is still the override if you ever apply from a machine.

### Detailed per-component maps

#### Control plane (FastAPI)

| Env var | Read in | Meaning | Set in | Default / fallback |
|---|---|---|---|---|
| `DATABASE_URL` | `database/db_engine.py` | Postgres connection string | ECS task env (from `local.db_password`); local `.env` | `postgresql://postgres:password@127.0.0.1:5432/makeway` |
| `APP_CREATION_QUEUE_URL` | `service/app_creation_queue.py` | SQS queue the control plane publishes to | ECS task env (`module.sqs.url`) | *(required)* |
| `SQS_REGION` | `service/app_creation_queue.py` | SQS region | ECS task env | `AWS_REGION` / `AWS_DEFAULT_REGION` |
| `SQS_ENDPOINT_URL` | `service/app_creation_queue.py` | LocalStack/SQS override (dev) | local `.env` | unset |
| `INTERNAL_API_KEY` | `dependencies/internal.py` | Shared secret for worker callbacks (fail-closed) | ECS task env (from `local.internal_api_key`) | unset → 401 on `/internal/*` |
| `JWT_SECRET_KEY` | `auth/jwt.py` | JWT signing key | ECS task env (from `local.app_secret_key`); local `.env` | auto-generated 48-char on apply |
| `JWT_ALGORITHM` | `auth/jwt.py` | JWT signing algorithm | — | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `auth/jwt.py` | Token lifetime | — | `30` |
| `GITOPS_REPO_URL` | `core/config.py` | GitOps repo URL (control-plane use) | — | `https://github.com/kapil4457/Makeway-IDP` |
| `LOG_LEVEL` | `core/logger.py` | Log level | ECS task env | `INFO` |
| `MAKEWAY_LOG_DIR` / `MAKEWAY_LOG_MAX_BYTES` / `MAKEWAY_LOG_BACKUPS` | `core/logger.py` | Log rotation | local | defaults in code |

#### Step-1 Lambda (GitHub Setup)

| Env var | Read in | Meaning | Set by | Default |
|---|---|---|---|---|
| `GITHUB_OWNER` | top of handler | GitHub owner for app repos + platform repo | module Lambda env (var default) | — |
| `GITHUB_TOKEN_SECRET_ID` | top of handler | Secrets Manager secret holding the PAT | module Lambda env | `makeway/github-pat` |
| `CONTROL_PLANE_URL` | top of handler | Internal API base URL | module `var.control_plane_url` (← CI/local) | — |
| `INTERNAL_API_KEY` | top of handler | Worker → control-plane shared key | module `var.internal_api_key` (auto-gen) | — |
| `MAKEWAY_PLATFORM_REPO` | top of handler | Platform repo name | module env | `Makeway-IDP` |
| `AWS_REGION` | top of handler | boto3 region | Lambda-managed | `ap-south-1` |

#### Step-2 Lambda (Crossplane / infra provisioning)

| Env var | Read in | Meaning | Set by | Default |
|---|---|---|---|---|
| `KUBE_API_ENDPOINT` | `step_2/handler.py:66` | Public kube-apiserver URL (pinggy TCP tunnel in front of `127.0.0.1:6443`) | module `var.kube_api_endpoint` ← **local tfvars / CI var** | — (required) |
| `KUBE_TOKEN` | `step_2/handler.py:68` | `makeway-worker` SA bearer token | module `var.kube_token` ← **local tfvars / CI secret** | — (required) |
| `KUBE_CA_CERT` | `step_2/handler.py:67`, `_kube_ssl_context()` | base64 CA cert for the exposed apiserver — **empty for the pinggy TCP tunnel** (raw TCP means the apiserver's self-signed cert can't match the pinggy hostname) | module `var.kube_ca_cert` | empty → TLS verification disabled (dev) |
| `CONTROL_PLANE_URL` / `INTERNAL_API_KEY` | top of handler | same as Step 1 | module env | — |
| `GITHUB_OWNER` / `GITHUB_TOKEN_SECRET_ID` / `MAKEWAY_PLATFORM_REPO` | top of handler | same as Step 1 | module env | `Makeway-IDP` |
| `SECRETS_PREFIX` | `step_2/handler.py:78` | Secrets Manager name prefix | module `var.secrets_prefix` | `makeway` |
| `RDS_PUBLICLY_ACCESSIBLE` | `step_2/handler.py:82` | Expose RDS publicly (local cluster) | module `var.rds_publicly_accessible` | `true` |
| `RDS_INGRESS_CIDR` | `step_2/handler.py:83` | 5432 ingress CIDR | module `var.rds_ingress_cidr` | `0.0.0.0/0` |
| `DEFAULT_REGION` / `AWS_REGION` | `step_2/handler.py:58-59` | AWS region for boto3 clients | module env | `ap-south-1` |

#### SQS-consumer Lambda

| Env var | Read in | Meaning | Set by | Default |
|---|---|---|---|---|
| `APP_CREATION_STATE_MACHINE_ARN` | `workers/sqs_consumer/handler.py:17` | State machine to start per message | module env (only set when ARN known) | empty → worker warns + skips |
| `AWS_REGION` | `workers/sqs_consumer/handler.py:14` | boto3 region | Lambda-managed | `ap-south-1` |

---

## Documentation map

| Doc | What's in it |
|---|---|
| [docs/design/Database.md](docs/design/Database.md) | Full schema, relationships, write-pattern |
| [docs/design/Deployment-Model.md](docs/design/Deployment-Model.md) | Why platform infra is push and user apps are pull |
| [docs/design/AWS-Service-Accounts.md](docs/design/AWS-Service-Accounts.md) | IAM service-account registry & least-privilege rules |
| [crossplane/README.md](crossplane/README.md) | How Crossplane expands capabilities into AWS resources |
| [argocd/external-secrets/README.md](argocd/external-secrets/README.md) | The ESO secret-delivery bootstrap |
| [terraform/BOOTSTRAP.md](terraform/BOOTSTRAP.md) | First-time AWS account bootstrap |
| [terraform/README.md](terraform/README.md) | The Terraform layout and state model |
| [app/control-plane/scripts/README.md](app/control-plane/scripts/README.md) | Operational CLIs for teams and users |