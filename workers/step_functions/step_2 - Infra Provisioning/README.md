# Step 2 — Infra Provisioning (Crossplane worker)

The Step-2 Lambda provisions the app's infrastructure by upserting **Crossplane XR instances** into the Kubernetes cluster of each requested **environment** (`{app}-{env}` namespace), polling them until `Ready+Synced`, then extracting the connection Secrets into AWS Secrets Manager and committing ExternalSecrets into gitops.

It reaches each cluster over **HTTPS through a tunnel** (localtunnel is the documented dev option — see [localTunnel/README.md](../../localTunnel/README.md)) to the **kube-apiserver** — it does not need a VPN or a VPC peering with your machine. The platform is **one cluster per environment** (qa/uat/prod): each cluster runs its own ArgoCD + Crossplane + ESO, is exposed through its own tunnel, and is **registered in the control-plane Cluster registry** with its endpoint, a `makeway-worker` bearer token, and (optionally) its CA bundle. The worker resolves per-capability which cluster to call from the registry — the Lambda env `KUBE_*` values are only the fallback for clusters without a registered token.

The steps below are a **per-cluster loop** — run 1–3, 5–6 once per environment:

1. [Architecture of the connection](#architecture-of-the-connection)
2. [Expose a cluster with localtunnel](#1-expose-the-cluster-with-localtunnel)
3. [Create the `makeway-worker` ServiceAccount + RBAC](#2-create-the-makeway-worker-serviceaccount--rbac)
4. [Get the CA bundle](#3-get-the-ca-bundle)
5. [Register the cluster in the control plane](#4-register-the-cluster-in-the-control-plane)
6. [Collect the values for Terraform (fallback cluster only)](#5-collect-the-values-for-terraform-fallback-cluster-only)
7. [Verify end-to-end](#6-verify-end-to-end)
8. [Security notes](#security-notes)

---

## Architecture of the connection

```
Step-2 Lambda (AWS)                              Your machine (each env cluster)
┌───────────────┐   HTTPS 443   ┌─────────────────┐   HTTPS    ┌────────────────────────┐
│ handler.py    │ ─────────────►│   loca.lt edge  │ ─────────► │  kube-apiserver :6443  │
│  (boto3 +     │  X-Internal-  │  terminates TLS │  (self-    │  (k3d/kind, local)     │
│   urllib)     │  API-Key to CP│  (*.loca.lt LE) │   signed)  └────────────────────────┘
└───────────────┘               └─────────────────┘   ok'd by
                                                     --allow-invalid-cert
        │
        │  GET /internal/requests/{id}  → per-capability
        │    kubeApiEndpoint / kubeToken / kubeCaCert  (from the Cluster registry)
        │  Authorization: Bearer <kubeToken>
        │  (ServiceAccount "makeway-worker" token, one per cluster)
        └──────────────────────────────────────────► /apis/makeway.io/v1beta1/...
                                                    /api/v1/namespaces/.../secrets
```

Three pieces must match **per cluster**:

| Piece | What it must point at | Provided via |
|---|---|---|
| Registered `kubeApiEndpoint` | `https://<subdomain>.loca.lt` — the public endpoint in front of `https://127.0.0.1:6443` (see step 1) | `POST /cluster/register` (step 4) |
| Registered `kubeToken` | A long-lived bearer token for that cluster's `makeway-worker` ServiceAccount (see step 2) | `POST /cluster/register` (step 4) |
| Registered `kubeCaCert` | Leave **empty** for the localtunnel dev setup (see step 3) | `POST /cluster/register` (step 4) |

The Lambda env `KUBE_API_ENDPOINT`/`KUBE_TOKEN`/`KUBE_CA_CERT` are now only the **fallback** (used when a cluster row has no token; also used by the health reporter's sweep) — see step 5.

---

## 1. Expose the cluster with localtunnel

The kube-apiserver by default **binds to `127.0.0.1:6443`** (e.g. `k3d cluster create` or `kind`). localtunnel gives it a public **HTTPS** endpoint on a `*.loca.lt` URL — no account, just an npm package.

> **What kind of tunnel is this?** localtunnel **terminates TLS at the loca.lt edge** with a valid Let's Encrypt certificate for `*.loca.lt`, then re-encrypts to your local apiserver (`--local-https`); `--allow-invalid-cert` skips validating kind's self-signed cert on *that* hop only. The Lambda sees the loca.lt certificate — which is why the endpoint is a plain HTTPS URL with no port suffix. (The old pinggy setup was raw TCP and presented the apiserver's own cert instead.)

**Start the tunnel** (see [localTunnel/README.md](../../localTunnel/README.md) for the full runbook):

```bash
npx localtunnel --port 6443 --local-https --allow-invalid-cert --subdomain makeway-kube
# -> https://makeway-kube.loca.lt
```

- `--subdomain` — **always set it**: the URL is stored in the cluster registry and the Lambda fallback env, and a random URL changes on every restart. Subdomains are first-come-first-served; if taken, pick another name.
- Keep the process **running** — if it dies, provisioning and health sweeps fail until it's back.

> **loca.lt consent page:** loca.lt serves a browser-facing interstitial; programmatic clients bypass it with a `Bypass-Tunnel-Reminder: true` header (any value) or a non-browser User-Agent. The workers send both. When testing with `curl`, add the header explicitly.

The endpoint is simply the printed URL:

```
https://makeway-kube.loca.lt        <- what localtunnel prints

KUBE_API_ENDPOINT = https://makeway-kube.loca.lt
```

> **Restart caveat:** with a fixed `--subdomain` the URL survives restarts — nothing to redo. If the subdomain was lost/taken and you switch names, **re-register the same `clusterName`** with the new endpoint — a same-environment re-registration refreshes the endpoint (and token/CA), so the control-plane registry stays current without any Terraform change (step 4).

After this step you should be able to, from another machine:

```bash
curl -s https://makeway-kube.loca.lt/version \
  -H "Bypass-Tunnel-Reminder: true"
# -> {"major":"1","minor":"27","gitVersion":"..."}
```

If you get HTML instead of JSON, the tunnel isn't up, the port is wrong, or you're seeing the loca.lt consent page (add the header above).

---

## 2. Create the `makeway-worker` ServiceAccount + RBAC

The Step-2 Lambda authenticates to the kube-apiserver with a **bearer token for a dedicated ServiceAccount**. Scope it as tightly as the worker needs:

- `get`/`create`/`patch` on **XR instances** (`makeway.io` group) in **all `{app}-{env}` namespaces**,
- `get` on **Secrets** and `create`/`patch` on the **`{claim}-creds` Secrets**,
- event/lease ops the API server requires for normal request handling (`events` in the SA's namespace).

Apply:

```yaml
# makeway-worker-sa.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: makeway-worker
  namespace: crossplane-system   # or a dedicated "makeway" namespace
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: makeway-worker
rules:
  - apiGroups: ["makeway.io"]
    resources: ["*"]
    verbs: ["get", "list", "watch", "create", "patch", "delete"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list", "create", "patch", "delete"]
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get", "list"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["create", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: makeway-worker
subjects:
  - kind: ServiceAccount
    name: makeway-worker
    namespace: crossplane-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: makeway-worker
```

> Note: `roleRef.apiGroup` is `rbac.authorization.k8s.io` — **not** `.../v1`. The
> API server rejects the version-qualified spelling.

```bash
kubectl apply -f makeway-worker-sa.yaml
```

> **Why `delete`?** The delete-app loop removes XR instances, and `_kube_upsert` uses merge-patch for idempotent updates. If you don't run app deletion, you can drop `delete`.

**Get the bearer token.** Kubernetes ≥1.24 no longer auto-creates a long-lived token Secret for a ServiceAccount, so create one explicitly:

```yaml
# makeway-worker-token.yaml
apiVersion: v1
kind: Secret
metadata:
  name: makeway-worker-token
  namespace: crossplane-system
  annotations:
    kubernetes.io/service-account.name: makeway-worker
type: kubernetes.io/service-account-token
```

```bash
kubectl apply -f makeway-worker-token.yaml
kubectl get secret makeway-worker-token -n crossplane-system -o jsonpath='{.data.token}' | base64 -d
# -> eyJhbGciOiJSUzI1NiIs...  (this is KUBE_TOKEN)
```

---

## 3. Get the CA bundle

The Lambda validates the TLS certificate before sending the bearer token — *if* you supply a CA. For the localtunnel dev setup the answer is:

**Leave `kube_ca_cert` empty.**

With localtunnel, the Lambda sees the **loca.lt edge's** certificate — a valid Let's Encrypt cert for `*.loca.lt` — so hostname checking would actually *match*. But the workers treat an empty CA as "verification disabled" (`_kube_ssl_context()` builds a no-verify context when no CA is given), which is the simplest dev configuration and works regardless of tunnel. The bearer token is still the auth boundary.

```python
# handler.py: _kube_ssl_context(ca_cert=None); None falls back to KUBE_CA_CERT
if ca:
    context.load_verify_locations(cadata=...)   # check_hostname stays True
else:
    logger.warning("no CA cert for this cluster API — TLS verification DISABLED.")
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
```

**If you want TLS verification ON**, you don't need an ingress like the raw-TCP setups did — the `*.loca.lt` certificate is real. Supply a CA bundle the chain verifies against (e.g. base64 of the ISRG Root X1 PEM) when registering the cluster, and the workers verify end-to-end against the tunnel hostname.

**TL;DR:** `kube_ca_cert = ""` for the dev setup. For a production control plane reaching a real cluster, terminate TLS on a real hostname and pin its CA (the same mechanism, with your own CA).

---

## 4. Register the cluster in the control plane

Each cluster's endpoint + token (+ optional CA) live in the **control-plane Cluster registry** — this is what the Step-2 worker reads per capability (`GET /internal/requests/{id}` returns `kubeApiEndpoint`/`kubeToken`/`kubeCaCert` per capability). Registration is a one-time `POST` per cluster:

```bash
curl -X POST $CONTROL_PLANE_URL/cluster/register \
  -H "Authorization: Bearer <your user JWT>" -H "Content-Type: application/json" \
  -d '{
        "clusterName": "qa-cluster",
        "kubeApiEndpoint": "https://<host>:<port>",
        "kubeToken": "<makeway-worker token from step 2>",
        "kubeCaCert": "",
        "environment": "qa"
      }'
```

- `environment` must be one of `qa` / `uat` / `prod` — app creation resolves each env to its cluster by this value.
- **Idempotent by `clusterName`**: re-running with the same name on the same environment **updates** endpoint/token/CA (this is how an endpoint change after a tunnel/subdomain change gets applied). Re-registering the same name on a *different* environment is rejected.
- `kubeCaCert` empty = TLS verification stays off (dev, step 3). When you add a TLS-terminating ingress in front of the apiserver, re-register with the real base64 CA bundle and the worker will verify.
- `kubeToken`/`kubeCaCert` are optional on purpose: a cluster registered without a token falls back to the Lambda env `KUBE_TOKEN`, and the worker keeps working. For three distinct clusters you will want a per-cluster token on each.

Verify it persisted (internal redacted endpoint — never returns the raw token):

```bash
curl -H "X-Internal-API-Key: <INTERNAL_API_KEY>" \
  $CONTROL_PLANE_URL/internal/clusters/qa-cluster
# -> {"clusterName":"qa-cluster","environment":"qa","kubeApiEndpoint":"https://...",
#     "hasToken":true,"hasCaCert":false}
```

> **Also bootstrap this cluster's GitOps side** before creating apps in this env: on each cluster run `kubectl apply -k argocd/clusters/<env>` (installs/points this cluster's ArgoCD at the env-scoped ApplicationSet + Crossplane + ESO). The single-cluster `argocd/root-application.yaml` is gone — delete the old `makeway-apps` ApplicationSet once on any cluster that had it.

---

## 5. Collect the values for Terraform (fallback cluster only)

The `terraform.tfvars` kube values no longer drive per-env routing — they feed the worker's **fallback** (`KUBE_API_ENDPOINT`/`KUBE_TOKEN`/`KUBE_CA_CERT`), used only when a registered cluster row has no token, and they feed the health reporter's single-cluster sweep. They still must be non-empty to apply the Terraform (a default cluster):

| `terraform.tfvars` var | Value | How to get it |
|---|---|---|
| `control_plane_url` | e.g. `http://<alb-dns>.elb.amazonaws.com` | your ALB / domain |
| `internal_api_key` | (leave empty → auto-generated) | — |
| `kube_api_endpoint` | `https://<subdomain>.loca.lt` from step 1 (any one cluster) | localtunnel terminal output |
| `kube_ca_cert` | **empty** (dev; see step 3) | — |
| `kube_token` | that cluster's `makeway-worker` token from step 2 | `kubectl get secret ... | base64 -d` |
| `github_owner` / `makeway_platform_repo` | as usual | GitHub |
| (no `github_pat` var) | the PAT lives only in Secrets Manager: `aws secretsmanager put-secret-value --secret-id makeway/github-pat --secret-string "ghp_…"` once, before first app creation | AWS CLI |
| `rds_publicly_accessible` | `true` for the local cluster / `false` for EKS | — |
| `rds_ingress_cidr` | empty = platform VPC CIDR from SSM (EKS); your machine's public IP (local cluster) | `curl ifconfig.me` |

They map 1:1 into the module's Lambda env vars ([terraform/modules/app_creation_step_functions/main.tf](https://github.com/kapil4457/Makeway-IDP/blob/main/terraform/modules/app_creation_step_functions/main.tf)):

```hcl
KUBE_API_ENDPOINT       = var.kube_api_endpoint   # fallback only
KUBE_CA_CERT            = var.kube_ca_cert        # fallback only
KUBE_TOKEN              = var.kube_token          # fallback only
```

---

## 6. Verify end-to-end

From the Lambda's perspective the connection has three boundaries per cluster; test each:

```bash
# 1. The tunnel is up and serving the kube-apiserver
curl -s https://<subdomain>.loca.lt/version -H "Bypass-Tunnel-Reminder: true"

# 2. The bearer token is valid against it
curl -s https://<subdomain>.loca.lt/apis/makeway.io/v1beta1 \
  -H "Bypass-Tunnel-Reminder: true" \
  -H "Authorization: Bearer <KUBE_TOKEN>" -H "Accept: application/json"
#    -> 200 {"kind":"APIResourceList", ...} — your RBAC allows listing the group

# 3. The worker can read a namespace you'll use
curl -s https://<subdomain>.loca.lt/api/v1/namespaces/order-service-qa \
  -H "Bypass-Tunnel-Reminder: true" \
  -H "Authorization: Bearer <KUBE_TOKEN>" -H "Accept: application/json"
#    -> 200 with the Namespace object (or 404 if it doesn't exist yet — that's fine)
```

If any of these fails, check: tunnel up? (localtunnel process still running — HTML answer instead of JSON often means the loca.lt consent page, add `Bypass-Tunnel-Reminder: true`), endpoint matches the printed URL?, token base64-decoded correctly? (`$ echo <KUBE_TOKEN> | base64 -d | jq .iss` should show the kube-apiserver's issuer)?

---

## Security notes

- **Least privilege the SA** — the Role above is the minimum the worker needs. Don't grant `cluster-admin`. Create it once **per cluster**.
- **The token is long-lived.** Rotate it by deleting the token Secret and recreating it (same annotations), then **re-register the cluster** with the new token. Registered tokens live in the control-plane `cluster` table (RDS encryption-at-rest); never put them in git. Re-registration is idempotent so a rotation is just one `POST`.
- **TLS verification stays OFF for the localtunnel dev setup** (`kube_ca_cert = ""`). That is dev-only — for a production control plane reaching a real cluster, terminate TLS on a real hostname and pin its CA (step 3).
- **The loca.lt URL is publicly reachable** by anyone who guesses the subdomain (no `allow_cidrs` on the free hosted server, and the apiserver itself still binds `127.0.0.1`). The bearer token is the boundary — keep it out of git, and rotate it if the endpoint is ever exposed to strangers.