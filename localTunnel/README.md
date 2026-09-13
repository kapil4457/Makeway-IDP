# localTunnel — exposing the local kind cluster to Makeway

The AWS workers (Step-2 Crossplane worker, ArgoCD health reporter) reach the
kube-apiserver over **HTTPS through a public tunnel**. This folder holds the
dev-seam pieces for the **localtunnel** (`loca.lt`) setup in front of the
local kind cluster:

| File | What it is |
|---|---|
| `makeway-worker-sa.yaml` | The `makeway-worker` ServiceAccount + least-privilege RBAC the workers authenticate with |
| `makeway-worker-token.yaml` | Long-lived token Secret for that ServiceAccount |
| `kubeconfig.yaml` | Local kind admin kubeconfig — **not in git** (cluster-admin creds) |

The full walkthrough (including the RBAC explanation) also lives in
[workers/step_functions/step_2 - Infra Provisioning/README.md](../workers/step_functions/step_2%20-%20Infra%20Provisioning/README.md);
this doc is the command-first runbook.

---

## 1. Start the tunnel

The kube-apiserver binds to `127.0.0.1:6443` (kind). localtunnel gives it a
public HTTPS endpoint:

```bash
npx localtunnel --port 6443 --local-https --allow-invalid-cert --subdomain makeway-kube
# -> https://makeway-kube.loca.lt
```

- `--port 6443` — the local apiserver port (check your kind kubeconfig's
  `server:` line if unsure).
- `--local-https` — the local end already speaks TLS (it's the apiserver);
  the tunnel re-encrypts to it instead of expecting plain HTTP.
- `--allow-invalid-cert` — kind's self-signed cert can't be validated on the
  tunnel→apiserver hop; this skips that check only.
- `--subdomain makeway-kube` — **always set it.** Without it every restart
  gets a random URL, and that URL is stored in the cluster registry and the
  Lambda fallback env. Subdomains are first-come-first-served; if the name is
  taken, pick another and redo steps 4–5 with it.

> Keep this process **running** — if it dies, provisioning and health sweeps
> fail until it's back up.

**What kind of tunnel is this?** Unlike a raw-TCP tunnel, localtunnel
*terminates TLS at the loca.lt edge* with a valid Let's Encrypt certificate
for `*.loca.lt`, then re-encrypts to your local apiserver. The client
(Lambda) sees the loca.lt certificate — so the endpoint is a plain HTTPS URL
with a normal port (`https://makeway-kube.loca.lt`, no port suffix).

## 2. Verify the tunnel from outside

```bash
curl -s https://makeway-kube.loca.lt/version \
  -H "Authorization: Bearer <token-from-step-3>" \
  -H "Accept: application/json" \
  -H "Bypass-Tunnel-Reminder: true"
# -> {"major":"1","minor":"...","gitVersion":"v1.xx.x"}
```

- `Bypass-Tunnel-Reminder` — loca.lt serves a consent/password page to
  browser-looking traffic; this header bypasses it (any value works). The
  workers already send it (plus a non-browser User-Agent).
- If you get HTML instead of JSON: tunnel down, wrong port, or the consent
  page — re-check `--subdomain` and the header.

## 3. Create the `makeway-worker` ServiceAccount + token (once per cluster)

```bash
kubectl apply -f localTunnel/makeway-worker-sa.yaml
kubectl apply -f localTunnel/makeway-worker-token.yaml

kubectl get secret makeway-worker-token -n crossplane-system \
  -o jsonpath='{.data.token}' | base64 -d
# -> eyJhbGciOiJSUzI1NiIs...  (this is KUBE_TOKEN)
```

## 4. Register (or refresh) the cluster in the control plane

```bash
curl -X POST $CONTROL_PLANE_URL/cluster/register \
  -H "Authorization: Bearer <your user JWT>" -H "Content-Type: application/json" \
  -d '{
        "clusterName": "qa-cluster",
        "kubeApiEndpoint": "https://makeway-kube.loca.lt",
        "kubeToken": "<makeway-worker token from step 3>",
        "kubeCaCert": "",
        "environment": "qa"
      }'
```

- **Idempotent by `clusterName`**: re-registering the same name on the same
  environment **updates** endpoint/token/CA in place — this is how an
  endpoint change gets applied without any Terraform change.
- `kubeCaCert` stays **empty** for the dev setup → TLS verification disabled
  in the workers (the bearer token is the auth boundary). See the upgrade
  path at the bottom if you want verification ON.
- Verify it persisted (redacted internal endpoint — never returns the token):

```bash
curl -H "X-Internal-API-Key: <INTERNAL_API_KEY>" \
  $CONTROL_PLANE_URL/internal/clusters/qa-cluster
# -> {"clusterName":"qa-cluster","environment":"qa",
#     "kubeApiEndpoint":"https://makeway-kube.loca.lt","hasToken":true,"hasCaCert":false}
```

> **Also bootstrap the cluster's GitOps side** once:
> `kubectl apply -k argocd/clusters/<env>` (this cluster's ArgoCD + the
> env-scoped ApplicationSet + Crossplane + ESO).

## 5. Update the Lambda fallback env

The workers resolve per-cluster creds from the registry at runtime (step 4 is
what matters). The `KUBE_*` env baked into the Lambdas is only the fallback —
keep it in sync anyway:

1. GitHub → repo **Settings → Secrets and variables → Actions → Variables**:
   set `MAKEWAY_KUBE_API_ENDPOINT = https://makeway-kube.loca.lt`
   (`MAKEWAY_KUBE_CA_CERT` stays unset/empty).
2. Run the **deploy-infra** workflow once (re-bakes the Lambda envs).
3. Locally (if you apply Terraform by hand): set `kube_api_endpoint` the same
   way in `terraform/terraform.tfvars` — see
   [terraform/terraform.tfvars.example](../terraform/terraform.tfvars.example).

## 6. When the tunnel restarts

- With `--subdomain` the URL survives restarts — nothing to do, just keep the
  process running.
- If the subdomain was lost/taken and you had to switch to a new name: update
  the **registry** (step 4, same `clusterName`) and the **Actions variable**
  (step 5). Both are one-POST / one-variable operations.

## Security notes

- **The bearer token is the boundary.** The loca.lt URL is publicly
  reachable by anyone who guesses the subdomain — least-privilege RBAC and a
  rotated token are what make that safe-ish. Dev only.
- **TLS verification stays OFF** (`kubeCaCert` empty) in the dev setup.
- **Upgrade path (verification ON):** because the Lambda sees a genuine
  `*.loca.lt` Let's Encrypt certificate, hostname checking *matches* — supply
  a CA bundle that covers it (e.g. base64 of the ISRG Root X1 PEM) when
  registering, and the workers verify TLS end-to-end instead of disabling it.
- Never commit `kubeconfig.yaml` or the worker token.
