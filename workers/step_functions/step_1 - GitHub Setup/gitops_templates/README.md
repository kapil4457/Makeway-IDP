# `argocd/apps/__APP_NAME__` — GitOps configuration

Managed by Makeway and stored in the Makeway platform repo itself — there is no
separate per-app gitops repository. The `makeway-apps` ApplicationSet (see
`argocd/root-application.yaml`) generates one ArgoCD Application per environment
overlay in this folder, so merging changes to `main` rolls the app out on the
cluster.

Layout:

- **`base/namespaces.yaml`** — one Kubernetes Namespace per environment
  (`__APP_NAME__-dev`, `__APP_NAME__-qa`, …). Imported by every env overlay.
- **`apps/<service>/`** — golden-path Deployment + Service (+ kustomization)
  for a service. Services are deduplicated by base name across environments
  (`orders-api-dev` and `orders-api-qa` share the `orders-api` folder).
- **`envs/<env>/`** — one overlay per environment. It binds the overlay's
  namespace and patches each service's image tag. A service's CI workflow edits
  `image:` in each `<service>-patch.yaml` after every merge to main; ArgoCD
  rolls out the change.

The image tags start as a placeholder. Set the `DOCKERHUB_IMAGE` repository
variable on the services repository (your Docker Hub account/repo) so CI writes
the real tag, then push a commit to `main` to trigger the first build.