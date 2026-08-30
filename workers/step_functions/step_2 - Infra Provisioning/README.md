# Step 2 — Infra Provisioning (Crossplane worker)

The Step-2 Lambda provisions the app's infrastructure by upserting **Crossplane XR instances** into the developer's Kubernetes cluster (`{app}-{env}` namespace), polling them until `Ready+Synced`, then extracting the connection Secrets into AWS Secrets Manager and committing ExternalSecrets into gitops.

It reaches your cluster over **HTTPS through a tunnel** (pinggy is the documented option) to the **kube-apiserver** — it does not need a VPN or a VPC peering with your machine. This file explains, in detail, the **local-cluster setup** that makes that possible:

1. [Architecture of the connection](#architecture-of-the-connection)
2. [Expose the cluster with pinggy](#1-expose-the-cluster-with-pinggy)
3. [Create the `makeway-worker` ServiceAccount + RBAC](#2-create-the-makeway-worker-serviceaccount--rbac)
4. [Get the CA bundle](#3-get-the-ca-bundle)
5. [Collect the values for Terraform](#4-collect-the-values-for-terraform)
6. [Verify end-to-end](#5-verify-end-to-end)
7. [Security notes](#security-notes)

---

## Architecture of the connection

```
Step-2 Lambda (AWS)                           Your machine (the cluster)
┌───────────────┐   HTTPS :<tcp-port>  ┌─────────┐  raw TCP   ┌────────────────────────┐
│ handler.py    │ ───────────────────► │  pinggy │ ─────────► │  kube-apiserver :6443   │
│  (boto3 +     │  X-Internal-         │  SSH    │            │  (k3d/kind, local)      │
│   urllib)     │  API-Key to CP       │  tunnel │            └────────────────────────┘
└───────────────┘                      └─────────┘
        │
        │   Authorization: Bearer <KUBE_TOKEN>
        │   (ServiceAccount "makeway-worker" token)
        └──────────────────────────────────────────► /apis/makeway.io/v1beta1/...
                                                    /api/v1/namespaces/.../secrets
```

Three pieces must match:

| The Lambda's env | What it must point at | Provided via |
|---|---|---|
| `KUBE_API_ENDPOINT` | `https://<pinggy-host>:<tcp-port>` — the public endpoint in front of `https://127.0.0.1:6443` (see step 1) | Terraform `kube_api_endpoint` |
| `KUBE_TOKEN` | A long-lived bearer token for the `makeway-worker` ServiceAccount (see step 2) | Terraform `kube_token` |
| `KUBE_CA_CERT` | Leave **empty** for the pinggy TCP tunnel (see step 3) | Terraform `kube_ca_cert` |

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

> **Free-plan caveat:** the public port is assigned per session, so `KUBE_API_ENDPOINT` in Terraform goes stale whenever the tunnel restarts. Restart the tunnel, read the new `<host>:<port>` from the output, and re-apply Terraform. There is no in-band re-registration today — keep the endpoint in `terraform.tfvars` in sync.

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
# handler.py: _kube_ssl_context()
if KUBE_CA_CERT:
    ... load_verify_locations(cadata=...)   # check_hostname stays True -> will NOT match the pinggy host
else:
    logger.warning("KUBE_CA_CERT is unset — TLS verification DISABLED.")
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
```

Empty is the only working dev configuration, and the bearer token is still the auth boundary.

**If you need TLS verification for real traffic**, don't chase a CA bundle against a raw TCP tunnel — put a **TLS-terminating ingress** in front of the apiserver instead (an HTTPS tunnel that presents a real certificate, or a public hostname + ACM cert), and set `kube_ca_cert` to the base64 of the CA that signed *that* endpoint's certificate.

**TL;DR:** `kube_ca_cert = ""` for the pinggy TCP setup. Dev-only; never ship that for a production control plane reaching a real cluster.

---

## 4. Collect the values for Terraform

| `terraform.tfvars` var | Value | How to get it |
|---|---|---|
| `control_plane_url` | e.g. `http://<alb-dns>.elb.amazonaws.com` | your ALB / domain |
| `internal_api_key` | (leave empty → auto-generated) | — |
| `kube_api_endpoint` | `https://<host>:<port>` from step 1 | pinggy terminal output |
| `kube_ca_cert` | **empty** (dev; see step 3) | — |
| `kube_token` | the `makeway-worker` token from step 2 | `kubectl get secret ... | base64 -d` |
| `github_owner` / `github_pat` / `makeway_platform_repo` | as usual | GitHub |
| `rds_publicly_accessible` | `true` for the local cluster / `false` for EKS | — |
| `rds_ingress_cidr` | your machine's public IP (local) / VPC CIDR (EKS) | `curl ifconfig.me` |

They map 1:1 into the module's Lambda env vars ([terraform/modules/app_creation_step_functions/main.tf](https://github.com/kapil4457/Makeway-IDP/blob/main/terraform/modules/app_creation_step_functions/main.tf)):

```hcl
KUBE_API_ENDPOINT       = var.kube_api_endpoint
KUBE_CA_CERT            = var.kube_ca_cert
KUBE_TOKEN              = var.kube_token
```

---

## 5. Verify end-to-end

From the Lambda's perspective the connection has three boundaries; test each:

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

- **Least privilege the SA** — the Role above is the minimum the worker needs. Don't grant `cluster-admin`.
- **The token is long-lived.** Rotate it by deleting the token Secret and recreating it (same annotations), then bump `kube_token` in Terraform.
- **TLS verification stays OFF for the pinggy TCP setup** (`kube_ca_cert = ""`). That is dev-only — for a production control plane reaching a real cluster, put a TLS-terminating ingress in front of the apiserver and pin its CA (step 3).
- **Firewall the tunnel if you can.** pinggy's free TCP tunnels don't expose `allow_cidrs`, and the apiserver itself still binds `127.0.0.1`, so the pinggy endpoint is the only public surface. The bearer token is the boundary — keep it out of git, and rotate it if the endpoint is ever exposed to strangers.