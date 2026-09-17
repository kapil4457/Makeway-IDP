# Makeway Documentation

> [Home](../README.md) › Documentation

Makeway is an internal developer platform: a developer requests an app with services
and capabilities, and the platform creates the GitHub monorepo, provisions the AWS
infrastructure through Crossplane, and rolls the app out through GitOps (ArgoCD).
The [root README](../README.md) tells that story in brief; the documents below are
the detailed, code-verified reference for each part of the system.

## Suggested reading order

1. **[Root README](../README.md)** — what Makeway is, the request lifecycle, the
   repository layout, and the full configuration reference.
2. **[App Flows](design/App-Flows.md)** — every flow walked end to end with no prior
   knowledge assumed: app creation, update, delete, Crossplane, ArgoCD, secrets,
   cluster bootstrap.
3. **[Deployment Model](design/Deployment-Model.md)** — why the platform is push and
   the apps are pull; the argument behind the two pipelines.
4. Component documents below, as needed.

## Design documents — `docs/design/`

| Document | Contents |
|---|---|
| [App Flows](design/App-Flows.md) | The complete walkthrough of every flow: golden-path creation, delta updates, environment deletes, the Crossplane and ArgoCD loops, the secret supply chain, and per-cluster bootstrap. Includes the deterministic naming rules the whole system hangs on. |
| [Database](design/Database.md) | The control-plane PostgreSQL schema: every table, the atomic app-creation write pattern, and the entity-relationship diagram. |
| [Deployment Model](design/Deployment-Model.md) | Why the platform's own infra is pushed by Terraform behind human approval while user apps are pulled by ArgoCD, and why GitOps lives in the platform repo. |
| [GitOps & CI Pipeline](design/GitOps-and-CI-Pipeline.md) | The app delivery chain: Step-1's GitOps emission, environment-scoped overlays, branch→environment promotion, CI credentials injection, cluster identity, the External Secrets bootstrap, and a troubleshooting table. |
| [AWS Service Accounts](design/AWS-Service-Accounts.md) | The IAM identity registry — what each account may touch, where its credentials live, and the least-privilege rules. |

## Component documentation

| Component | Document | Contents |
|---|---|---|
| Control plane (FastAPI) | [app/control-plane/README.md](../app/control-plane/README.md) | API surface, running it locally, structure map, regression commands. |
| └ Operational CLIs | [app/control-plane/scripts/README.md](../app/control-plane/scripts/README.md) | Creating users/teams/memberships from the command line. |
| └ Database migrations | [app/control-plane/migrations/README.md](../app/control-plane/migrations/README.md) | The Alembic workflow and command reference. |
| Frontend console (React) | [app/frontend/README.md](../app/frontend/README.md) | Pages, API wiring, local dev, deployment. |
| Step-2 worker (Crossplane) | [workers/step_functions/step_2 - Infra Provisioning/README.md](../workers/step_functions/step_2%20-%20Infra%20Provisioning/README.md) | How the worker reaches each cluster: tunnels, `makeway-worker` RBAC, cluster registration, verification. |
| Crossplane configurations | [crossplane/README.md](../crossplane/README.md) | XRDs + Compositions per capability, bootstrap per cluster, design decisions. |
| External Secrets Operator | [argocd/external-secrets/README.md](../argocd/external-secrets/README.md) | The secret-delivery bootstrap: ClusterSecretStore, install Applications, EKS migration path. |
| Terraform | [terraform/README.md](../terraform/README.md) | Root/bootstrap layout, state model, module catalogue, platform CI/CD. |
| └ First-time bootstrap | [terraform/BOOTSTRAP.md](../terraform/BOOTSTRAP.md) | From an empty AWS account: state bucket, OIDC identity, first apply, GitHub secrets. |
| Cluster tunnel (dev) | [localTunnel/README.md](../localTunnel/README.md) | Command-first runbook for exposing a local cluster's kube-apiserver: the loca.lt relay, plus the [bastion reverse tunnel](../localTunnel/bastion-tunnel.md) alternative (in-VPC path, stable endpoint, workers-only reachability). |

## Diagrams — `docs/diagrams/`

| File | Contents |
|---|---|
| [`Flow Diagram.drawio`](diagrams/Flow%20Diagram.drawio) | High-level request flow and user flow. |
| [`Makeway Platform Infra.drawio`](diagrams/Makeway%20Platform%20Infra.drawio) | The platform's AWS infrastructure. |
| [`Makeway platform - CICD Flow.drawio`](diagrams/Makeway%20platform%20-%20CICD%20Flow.drawio) | The CI/CD pipeline, including the OIDC deploy flow. |

The `.drawio` sources are tracked; rendered exports (`.svg`/`.jpg`) are gitignored —
open the sources in [draw.io](https://app.diagrams.net).

## Conventions used throughout the docs

- **Environments are `qa` / `uat` / `prod`** (no `dev`); branches map
  `feature/* → qa`, `release/* → uat`, `main → prod`.
- **camelCase everywhere** in models, DTOs, and API payloads' attributes.
- **Idempotency is the contract**: deterministic names, upserts, and diff-before-write
  at every layer — retries never duplicate resources.
- **Secrets never land in git**: bootstrap-only credentials are excluded from every
  kustomization root; app credentials travel ExternalSecret → Secrets Manager → K8s
  Secret only.
