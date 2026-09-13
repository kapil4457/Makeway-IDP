# Step 2 — Infra Provisioning (Crossplane worker)

The Step-2 Lambda provisions the app's infrastructure by upserting **Crossplane XR instances** into the Kubernetes cluster of each requested **environment** (`{app}-{env}` namespace), polling them until `Ready+Synced`, then extracting the connection Secrets into AWS Secrets Manager and committing ExternalSecrets into gitops.

It reaches each cluster over **HTTPS through a tunnel** (pinggy is the documented option) to the **kube-apiserver** — it does not need a VPN or a VPC peering with your machine. The platform is **one cluster per environment** (qa/uat/prod): each cluster runs its own ArgoCD + Crossplane + ESO, is exposed through its own tunnel, and is **registered in the control-plane Cluster registry** with its endpoint, a `makeway-worker` bearer token, and (optionally) its CA bundle. The worker resolves per-capability which cluster to call from the registry — the Lambda env `KUBE_*` values are only the fallback for clusters without a registered token.

The steps below are a **per-cluster loop** — run 1–3, 5–6 once per environment:

1. [Architecture of the connection](#architecture-of-the-connection)
2. [Expose a cluster with pinggy](#1-expose-the-cluster-with-pinggy)
3. [Create the `makeway-worker` ServiceAccount + RBAC](#2-create-the-makeway-worker-serviceaccount--rbac)
4. [Get the CA bundle](#3-get-the-ca-bundle)
5. [Register the cluster in the control plane](#4-register-the-cluster-in-the-control-plane)
6. [Collect the values for Terraform (fallback cluster only)](#5-collect-the-values-for-terraform-fallback-cluster-only)
7. [Verify end-to-end](#6-verify-end-to-end)
8. [Security notes](#security-notes)

---

## Architecture of the connection

```
Step-2 Lambda (AWS)                           Your machine (each env cluster)
┌───────────────┐  HTTPS :<tcp-port>  ┌─────────┐  raw TCP   ┌────────────────────────┐
│ handler.py    │ ───────────────────► │  pinggy │ ─────────► │  kube-apiserver :6443   │
│  (boto3 +     │  X-Internal-         │  SSH    │            │  (k3d/kind, local)      │
│   urllib)     │  API-Key to CP       │  tunnel │            └────────────────────────┘
└───────────────┘                      └─────────┘
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
| Registered `kubeApiEndpoint` | `https://<pinggy-host>:<tcp-port>` — the public endpoint in front of `https://127.0.0.1:6443` (see step 1) | `POST /cluster/register` (step 4) |
| Registered `kubeToken` | A long-lived bearer token for that cluster's `makeway-worker` ServiceAccount (see step 2) | `POST /cluster/register` (step 4) |
| Registered `kubeCaCert` | Leave **empty** for the pinggy TCP tunnel (see step 3) | `POST /cluster/register` (step 4) |

The Lambda env `KUBE_API_ENDPOINT`/`KUBE_TOKEN`/`KUBE_CA_CERT` are now only the **fallback** (used when a cluster row has no token; also used by the health reporter's single-cluster sweep) — see step 5.

---

## 1. Expose the cluster with pinggy

The kube-apiserver by default **binds to `127.0.0.1:6443`** (e.g. `k3d cluster create` or `kind`). pinggy gives it a public **TCP** endpoint via an SSH reverse tunnel — no account, no agent.

> **What kind of tunnel is this?** The command below uses `+tcp`, a **raw TCP forward**: pinggy does **not terminate TLS**. The kube-apiserver itself performs the TLS handshake and presents its *own* certificate. That is why step 3 sets `kube_ca_cert` to empty.

**Start the tunnel:**

```bash
ssh -p 443 -R0:127.0.0.1:6443 \
  -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
  <PINGGY_TOKEN>+tcp@free.pinggy.io
```

- `-R0:127.0.0.1:6443` — forward a public port back to the local apiserver. `0` lets pinggy assign the public port.
- `<PINGGY_TOKEN>+tcp` — your personal pinggy token (shown by the pinggy app for your account) with the `+tcp` suffix for a raw TCP tunnel (no TLS termination, no HTTP layer at pinggy).
- `ServerAliveInterval=30` keeps the tunnel alive across idle time.

On connect, pinggy prints the public endpoint as a `tcp://<host>:<port>` line. Read `<host>:<port>` from it — that is your kube endpoint:

```
tcp://<host>:<port>                  <- what pinggy prints

KUBE_API_ENDPOINT = https://<host>:<port>     (https, not tcp)
```

> **Free-plan caveat:** the public port is assigned per session, so the registered endpoint goes stale whenever the tunnel restarts. Restart the tunnel, read the new `<host>:<port>` from the output, and **re-register the same `clusterName`** — a same-environment re-registration refreshes the endpoint (and token/CA), so the control-plane registry stays current without any Terraform change (step 4).

After this step you should be able to, from another machine:

```bash
curl -k https://<host>:<port>/version
# -> {"major":"1","minor":"27","gitVersion":"..."}
```

If `curl` hangs or refuses, the tunnel isn't up / the forwarded port is wrong.

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

The Lambda validates the TLS certificate before sending the bearer token — *if* you supply a CA. For the pinggy **TCP** tunnel the answer is simple:

**Leave `kube_ca_cert` empty.**

Because pinggy only forwards raw TCP, the certificate the Lambda sees is the **kube-apiserver's own** (self-signed for a local kind/k3d cluster). Its Subject Alternative Names are `kubernetes`, `kubernetes.default.svc`, `localhost`, `127.0.0.1` and the cluster IPs — **never** `<host>`. The handler's `_kube_ssl_context()` keeps hostname checking on whenever a CA is provided, so no CA bundle — not even the cluster's own — survives the hostname check against the pinggy endpoint:

```python
# handler.py: _kube_ssl_context(ca_cert=None); None falls back to KUBE_CA_CERT
if ca:
    context.load_verify_locations(cadata=...)   # check_hostname stays True -> will NOT match the pinggy host
else:
    logger.warning("no CA cert for this cluster API — TLS verification DISABLED.")
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
```

Empty is the only working dev configuration, and the bearer token is still the auth boundary.

**If you need TLS verification for real traffic**, don't chase a CA bundle against a raw TCP tunnel — put a **TLS-terminating ingress** in front of the apiserver instead (an HTTPS tunnel that presents a real certificate, or a public hostname + ACM cert), and set `kube_ca_cert` to the base64 of the CA that signed *that* endpoint's certificate.

**TL;DR:** `kube_ca_cert = ""` for the pinggy TCP setup. Dev-only; never ship that for a production control plane reaching a real cluster.

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
- **Idempotent by `clusterName`**: re-running with the same name on the same environment **updates** endpoint/token/CA (this is how a pinggy endpoint change after a tunnel restart gets applied). Re-registering the same name on a *different* environment is rejected.
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
| `kube_api_endpoint` | `https://<host>:<port>` from step 1 (any one cluster) | pinggy terminal output |
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
curl -k https://<host>:<port>/version

# 2. The bearer token is valid against it
curl -k https://<host>:<port>/apis/makeway.io/v1beta1 \
  -H "Authorization: Bearer <KUBE_TOKEN>" -H "Accept: application/json"
#    -> 200 {"kind":"APIResourceList", ...} — your RBAC allows listing the group

# 3. The worker can read a namespace you'll use
curl -k https://<host>:<port>/api/v1/namespaces/order-service-qa \
  -H "Authorization: Bearer <KUBE_TOKEN>" -H "Accept: application/json"
#    -> 200 with the Namespace object (or 404 if it doesn't exist yet — that's fine)
```

If any of these fails, check: tunnel up? (`pinggy` still running / SSH session connected), endpoint host & port match?, token base64-decoded correctly? (`$ echo <KUBE_TOKEN> | base64 -d | jq .iss` should show the kube-apiserver's issuer)?

---

## Security notes

- **Least privilege the SA** — the Role above is the minimum the worker needs. Don't grant `cluster-admin`. Create it once **per cluster**.
- **The token is long-lived.** Rotate it by deleting the token Secret and recreating it (same annotations), then **re-register the cluster** with the new token. Registered tokens live in the control-plane `cluster` table (RDS encryption-at-rest); never put them in git. Re-registration is idempotent so a rotation is just one `POST`.
- **TLS verification stays OFF for the pinggy TCP setup** (`kube_ca_cert = ""`). That is dev-only — for a production control plane reaching a real cluster, put a TLS-terminating ingress in front of the apiserver and pin its CA (step 3).
- **Firewall the tunnel if you can.** pinggy's free TCP tunnels don't expose `allow_cidrs`, and the apiserver itself still binds `127.0.0.1`, so the pinggy endpoint is the only public surface. The bearer token is the boundary — keep it out of git, and rotate it if the endpoint is ever exposed to strangers.