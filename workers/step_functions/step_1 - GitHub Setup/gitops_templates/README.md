# `argocd/apps/__APP_NAME__` — GitOps configuration

Managed by Makeway and stored in the Makeway platform repo itself — there is no
separate per-app gitops repository. The `makeway-apps` ApplicationSet (see
`argocd/root-application.yaml`) generates one ArgoCD Application per environment
overlay in this folder, so merging changes to `main` rolls the app out on the
cluster.

Layout:

- **`base/`** — what every env overlay shares: `network-policies.yaml`
  (per-namespace isolation: a `default-deny-ingress` policy plus an
  `allow-same-namespace-ingress` policy, so a pod in another app's namespace
  (e.g. `swiggy-qa`) cannot reach a pod in this app's namespace even if it
  learns its ClusterIP). **Requires a policy-capable CNI (calico/cilium, not
  the default k3d/kind flannel/kindnet) to be enforced.**
- **`envs/<env>/namespace.yaml`** — each overlay creates exactly one Kubernetes
  Namespace, its own `__APP_NAME__-<env>` (qa → `__APP_NAME__-qa`). The qa
  Application never manages uat/prod, and vice versa.
- **`apps/<service>/`** — golden-path Deployment + Service (+ kustomization)
  for a service. Services are deduplicated by base name across environments
  (`orders-api-qa` and `orders-api-prod` share the `orders-api` folder).
- **`envs/<env>/`** — one overlay per environment. It binds the overlay's
  namespace and patches each service's image tag. A service's CI workflow edits
  `image:` in that environment's `<service>-patch.yaml` on every merge to the
  branch that promotes it. The environments are managed by branch:
  `feature/*` → `qa`, `release/*` → `uat`, `main` → `prod`. ArgoCD rolls out
  the change.

The image tags start as a placeholder. Set the `DOCKERHUB_IMAGE` repository
variable on the services repository (your Docker Hub account/repo) so CI writes
the real tag, then push a commit to `main` to trigger the first build.