# GitOps & CI Pipeline

How an application goes from an approved create-request to running pods, and how each
link in that chain is wired: the Step-1 worker's GitOps emission, the app repos' CI,
the ArgoCD ApplicationSets, and the External Secrets bootstrap.

---

## 1. Delivery pipeline

```
POST /app/create (idempotency key)
  └─ control plane: rows + SQS makeway-requests
       └─ SQS consumer → Step Functions
            ├─ Step 1 (GitHub Setup Lambda)
            │    ├─ creates the services monorepo (golden-path scaffolds)
            │    ├─ injects CI credentials (see §5)
            │    ├─ pushes the scaffold (CI fires on push)
            │    └─ publishes argocd/apps/<app>/ to the platform repo (see §2)
            └─ Step 2 (Provisioning Lambda)
                 └─ applies Crossplane claims into {app}-{env}, extracts
                    connection secrets, commits ExternalSecrets into gitops
CI (per service repo, ci-<service>.yaml)
  └─ on merge to the env's branch: buildx build + push to Docker Hub
     (:svc-<sha> immutable + :svc-latest floating),
     then bump argocd/apps/<app>/envs/<env>/<svc>-patch.yaml on platform main
ArgoCD (per cluster, one env ApplicationSet)
  └─ makeway-apps-<env> globs argocd/apps/*/envs/<env> → Application
     <app>-<env> → syncs into namespace {app}-{env}, automated prune+selfHeal
```

## 2. GitOps layout per app

`argocd/apps/<appName>/` in the platform repo (`workers/step_functions/step_1 - GitHub
Setup/handler.py`, `_argocd_app_files`):

| Path | Contents |
|---|---|
| `README.md` | generated doc |
| `base/` | netpols (default-deny ingress + same-namespace allow) — **not** namespaces |
| `apps/<svc>/` | Deployment (placeholder image) + Service + kustomization, shared across envs |
| `envs/<env>/` | `namespace.yaml` (`{app}-{env}`), `kustomization.yaml`, per-svc `<svc>-patch.yaml` |

The patch file is **CI-owned after the first build** — Step-1 carries the current file
over from platform main instead of re-rendering the placeholder, so CI bumps and
Step-2's `inject/` + `external-secrets/` entries survive re-runs.

### Environment-scoped overlays

Overlays are emitted **only for the environments the application targets** — the
control plane derives those from the distinct `cluster.environment` across the app's
services (`internal_api_service.get_request_details`), and Step-1 intersects them with
the canonical qa/uat/prod tiers. This keeps an app's GitOps surface equal to its actual
footprint:

- A prod-only application never grows qa/uat overlays, so a qa cluster's
  ApplicationSet never instantiates an Application for it — placeholder-image pods
  never appear in environments the app was never promoted to.
- Environments that fall **out** of the app's set but whose overlay already exists on
  main are **trimmed via `delete_paths`** on the app's next update request — dropping
  the overlay deletes the Application and ArgoCD cascades the namespace away.
- Guards: `app_envs=None` preserves the historical all-tiers behavior; a non-canonical
  env set falls back to all tiers with a warning, so an app's GitOps is never silently
  stripped in one push. Covered by `_smoke_step1.py` §17.

## 3. Environments and image promotion

| Branch | Environment | CI bumps |
|---|---|---|
| `feature/*` | qa | `envs/qa/<svc>-patch.yaml` |
| `release/*` | uat | `envs/uat/<svc>-patch.yaml` |
| `main` | prod | `envs/prod/<svc>-patch.yaml` |

CI pushes **two tags** per build: `:<svc>-<github-sha>` (immutable, what the gitops
patch pins — traceability + git-revert rollback) and `:<svc>-latest` (floating). The
patch bump lands on platform main with `[skip ci]`; ArgoCD syncs the sha tag. A patch
showing `makeway-placeholder/<svc>:pending-first-build` means **nothing has been
promoted to that environment** — merge code to the env's branch.

## 4. Cluster identity

A cluster's GitOps identity is decided by **which bundle was `kubectl apply -k`'d to
it**. Each `argocd/clusters/<env>/` root installs exactly one env ApplicationSet
(`makeway-apps-<env>`) that globs only `argocd/apps/*/envs/<env>`.

Bootstrap or switch a cluster's environment:

```bash
kubectl apply -k argocd/clusters/prod                  # make it a prod cluster
kubectl delete applicationset makeway-apps-qa -n argocd  # drop the qa set (generated
                                                       # Applications + namespaces cascade away)
```

Verify with `kubectl get applicationsets -n argocd` — the ApplicationSet name
(`makeway-apps-<env>`) is the identity.

**Split-brain:** the Cluster DB says `environment=prod` (Step-2 provisions into
`{app}-prod`, CI bumps prod patches) while ArgoCD runs the qa bundle → the cluster
serves `app-1-qa` with placeholder images. The two identities disagree; fix the
bundle, not the DB row.

## 5. CI credentials (Secrets Manager → GitHub Actions)

Seeded once in `makeway/app-repo-ci` (JSON: `dockerhub_image`, `dockerhub_username`,
`dockerhub_token`); the PAT lives in `makeway/github-pat`. The Step-1 worker injects
them into every repo it creates or updates (`_inject_repo_ci_config`):

- 3 repo **secrets** (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `GITOPS_PAT`) —
  sealed-box encrypted with the repo's public key; PyNaCl is **vendored into the Lambda
  zip** by deploy-infra (`--target` must be **absolute** — a relative target under the
  plan job's `working-directory: terraform` installs outside the zipped source and
  ships a nacl-less zip that silently skips injection; deploy-infra asserts the zip
  carries `nacl/`).
- 1 repo **variable** (`DOCKERHUB_IMAGE`) — repo *variables* have **no create-or-update
  PUT** (only repo secrets do): the worker `POST`s the variable and `PATCH`es on 409.
- Warn-and-continue: missing secret/keys or a GitHub failure logs a warning and the
  repo is still created; the **next update request self-heals** the config.

## 6. External Secrets bootstrap

Three pieces per cluster (canonical in `argocd/external-secrets/`, tracked copies in
`argocd/clusters/base/`):

1. `external-secrets` — Helm chart app (ESO operator). `targetRevision` is a semver
   range (`>=0.10.0 <0.20.0`).
2. `makeway-external-secrets-store` — kustomize root with the `makeway`
   ClusterSecretStore (cluster-scoped, AWS Secrets Manager, static-credential mode on
   the local cluster — an EKS/IRSA migration swaps only the store's auth; every
   ExternalSecret stays untouched). The `aws-credentials` Secret is bootstrap-only and
   deliberately **excluded from the kustomization** so ArgoCD never re-renders live
   keys.
3. Every capability's ExternalSecret — committed by Step-2 extract from
   `claim_templates/external-secret.yaml` into `envs/<env>/external-secrets/`.

Two constraints apply to any (re)bootstrap of this stack:

- **`ServerSideApply=true`** is required in `eso-install-application.yaml` syncOptions.
  ArgoCD's default client-side apply stores the whole manifest in the
  `last-applied-configuration` annotation; ESO 0.19.x CRDs exceed etcd's 256 KB
  annotation limit, so both core CRDs are rejected
  (`metadata.annotations: Too long: may not be more than 262144 bytes`) and the
  operator never installs. Server-side apply bypasses the annotation entirely.
- **`apiVersion: external-secrets.io/v1`** (not `v1beta1`) is required in the store
  manifest and the Step-2 ExternalSecret template. ESO 0.19.x CRDs serve **only v1**;
  a v1beta1 manifest fails ArgoCD sync discovery
  (`failed to discover server resources for group version external-secrets.io/v1beta1`)
  even after the CRDs exist. Both
  `argocd/external-secrets/cluster-secret-store.yaml` and
  `workers/step_functions/step_2 - Infra Provisioning/claim_templates/external-secret.yaml`
  follow this.

## 7. Accessing a deployed app (local cluster)

Local clusters expose no Ingress — access runs through a port-forward on the service:

```bash
kubectl --context kind-kind -n <app>-<env> port-forward svc/<service> 8080:80
# http://localhost:8080  (FastAPI: /docs)
```

## 8. Troubleshooting reference

| Symptom / error | Meaning | Fix |
|---|---|---|
| Lambda log: `No module named 'nacl'` | Step-1 zip shipped without PyNaCl → Actions-config injection skipped | vendor step's absolute `--target` + zip assert in deploy-infra |
| buildx: `invalid tag ":fast-api-latest"` | repo variable `DOCKERHUB_IMAGE` missing while secrets landed | variable POST/PATCH fix; re-run the app's update request |
| CRD: `metadata.annotations: Too long` | client-side apply of >256 KB ESO CRDs | `ServerSideApply=true` on the ESO app |
| sync: `failed to discover ... external-secrets.io/v1beta1` | manifest uses the apiVersion ESO 0.19.x dropped | use `external-secrets.io/v1` |
| pods `ImagePullBackOff` with `makeway-placeholder/...` image | that env was never promoted | merge to the env's branch (feature/*→qa, release/*→uat, main→prod) |
| app in the "wrong" env on a cluster | cluster runs the wrong env ApplicationSet | apply the right `argocd/clusters/<env>` bundle, delete the old ApplicationSet |
| store app `Missing` | tracked ClusterSecretStore absent — usually ESO not installed (see §6 constraints) | resolve the ESO chain first, then Sync |

## 9. Known limitations

- **No Ingress on local clusters** — application access is via port-forward (§7);
  an Ingress controller is the follow-up for shared access.
- **ESO chart version range** — the `external-secrets` app tracks a semver range;
  pin the resolved version once validated to prevent auto-bumping past a breaking
  change.
- **Tunnel-based cluster access for provisioning** — the Step-2 Lambda reaches
  workload clusters through `localTunnel/kubeconfig.yaml`; the tunnel must be up
  before creating applications with capabilities.
