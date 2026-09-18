# Bastion reverse tunnel — alternative to the loca.lt tunnel

> [Documentation index](../docs/README.md) › Components › Cluster tunnel (dev)

The [loca.lt runbook](README.md) exposes the local kind cluster through a
public third-party relay. This document is the alternative: an SSH **reverse
tunnel** through the platform's own bastion host. The cluster stays 100%
local in both setups — only the path from the AWS workers to the
kube-apiserver changes.

| | loca.lt relay | Bastion reverse tunnel |
|---|---|---|
| Path | workers → public loca.lt relay → laptop | workers → bastion (private IP, in-VPC) → laptop |
| Third party in the path | yes — the relay terminates TLS with a `*.loca.lt` cert | no — raw TCP inside SSH; the apiserver's own TLS is end-to-end |
| Reachable by | anyone who guesses the subdomain (bearer token is the only boundary) | only traffic from the workers' security group reaches 6443 |
| Endpoint | `https://makeway-kube.loca.lt` (subdomain must be re-claimed each era) | `https://<bastion-private-ip>:6443` — stable for the instance's lifetime |
| Reconfigure after a tunnel restart | re-register if the subdomain was lost | nothing — the endpoint never moves |
| Setup cost | `npx localtunnel` only | SSH key on the bastion, one SG rule, `GatewayPorts` in sshd |
| Common requirement | the laptop must stay awake; when it sleeps, provisioning and health sweeps fail until it's back | same |

Steps at a glance:

| When | What |
|---|---|
| Once, ever | §1 Terraform apply → §2 sshd config → §5 register |
| Every dev session | §3 — two terminals, two commands |
| Tunnel dropped / laptop rebooted | §3 again — the endpoint never moves, nothing to re-register |
| Infra destroyed and re-applied | §2 (fresh instance) + §5 (new private IP) — the SG rule and key pair return with the apply itself |

## Quick reference — all steps, in order

1. Commit and push the platform changes: the `bastion_kubeapi_from_workers`
   SG rule, the key-pair variable, and the CI key-staging step.
2. Set the SSH public key for the bastion — `bastion_ssh_public_key` (the
   full `ssh-ed25519 AAAA...` line) in `terraform.tfvars` (local applies) or
   the repo Actions variable `MAKEWAY_BASTION_SSH_PUBLIC_KEY` (CI applies).
3. `terraform apply` — creates the bastion key pair and the 6443-from-workers
   SG rule. On a bastion that was created without a key, the key-pair
   addition replaces the instance: new instance id and private IP, so redo
   steps 5, 6, 10, 11.
4. Open an SSM shell to the bastion:
   `aws ssm start-session --target <bastion-instance-id> --region <region> --profile <profile>`
5. One-time sshd config on the bastion:
   `echo 'GatewayPorts clientspecified' | sudo tee /etc/ssh/sshd_config.d/40-gatewayports.conf && sudo systemctl restart sshd`
6. Get the bastion private IP:
   `aws ec2 describe-instances --region <region> --profile <profile> --filters Name=tag:Name,Values=makeway-bastion Name=instance-state-name,Values=running --query "Reservations[].Instances[].PrivateIpAddress" --output text`
7. Terminal 1 (every dev session):
   `aws ssm start-session --target <bastion-instance-id> --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["22"],"localPortNumber":["2222"]}' --region <region> --profile <profile>`
8. Terminal 2 (every dev session):
   `ssh -N -p 2222 -R 0.0.0.0:6443:127.0.0.1:6443 <bastion-user>@127.0.0.1 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes`
9. Verify on the bastion: `ss -tlnp | grep 6443` must show `0.0.0.0:6443`,
   and `curl -sk https://<bastion-private-ip>:6443/version` must return JSON.
10. Register or refresh the cluster endpoint: POST to `/cluster/register`
    with the same `clusterName` and
    `kubeApiEndpoint = https://<bastion-private-ip>:6443` (omit
    `kubeToken`/`kubeCaCert` to keep stored values).
11. Set the worker fallback env (`MAKEWAY_KUBE_API_ENDPOINT`) to the same
    `https://<bastion-private-ip>:6443` and run the **deploy-infra** workflow
    once.
12. Repeat forever: only steps 7–8 per session. After a destroy + re-apply:
    repeat steps 5, 6, 10, 11 only — plus reset the laptop's host-key record
    for the replaced instance: `ssh-keygen -R "[127.0.0.1]:2222"` (a replaced
    instance has a new host key; the first reconnect must re-accept it).

## Architecture

```
Step-2 / health reporter (Lambda, private subnets)
        │  https://<bastion-private-ip>:6443
        ▼
bastion sshd :6443  ←── SSH session (-R) ──  laptop
                                                    │ 127.0.0.1:6443
                                                    ▼
                                              kind kube-apiserver
```

The laptop holds an SSH session to the bastion and asks sshd to bind
`0.0.0.0:6443` on the bastion (`-R`). The workers — VPC-attached in private
subnets — connect to the bastion's *private* IP, so the apiserver endpoint is
never publicly exposed. Bytes that arrive on the bastion travel back through
the SSH session to the laptop and land on `127.0.0.1:6443`, where kind
listens.

## 1. One-time AWS setup (Terraform)

The platform root ships everything this tunnel needs — apply with the
platform root:

- `aws_security_group_rule.bastion_kubeapi_from_workers` ([main.tf](../terraform/main.tf))
  — ingress `tcp/6443` on the bastion, scoped to the workers' security group.
  Never widen it to the internet.
- `aws_key_pair.bastion` — created once `bastion_ssh_public_key` carries an
  SSH public key: the full `ssh-ed25519 AAAA...` line, not a path — the
  variable holds the key *content* so both local and CI applies can supply it.

  ```hcl
  # local apply — terraform/terraform.tfvars (never committed)
  bastion_ssh_public_key = "ssh-ed25519 AAAA... operator@laptop"
  ```

  CI applies read it from the repo Actions variable
  `MAKEWAY_BASTION_SSH_PUBLIC_KEY` — a public key is not a secret, so a
  plain Actions variable is the right home. An empty value silently skips
  the key pair (the resource is `count`-gated): an apply without it deploys
  a bastion the tunnel's sshd leg cannot authenticate to.
- **Adding a key pair to a bastion created without one REPLACES the
  instance** (`key_name` is ForceNew) — the instance id and private IP
  change, so §2 and §5 must be redone. A deploy that carries the key from
  the start creates the instance with it and never replaces. The SG rule,
  by contrast, is a standalone resource and always attaches without
  replacement.

Direct-SSH setups (option A in §3) additionally need ingress `tcp/22` from
the operator's IP and an EIP for a stable target; the SSM-brokered default
needs neither. Within an instance's lifetime the **private** IP — what the
workers and the cluster registry use — is stable; across a replacement
(including a key-pair addition) it is not.

## 2. One-time sshd config on the bastion

By default sshd binds `-R` forwards to loopback only; the workers need
`0.0.0.0:6443`. Open an SSM session and set `GatewayPorts`:

```bash
aws ssm start-session --target <bastion-instance-id> --region us-east-1 --profile makeway

# on the bastion:
echo 'GatewayPorts clientspecified' | sudo tee /etc/ssh/sshd_config.d/40-gatewayports.conf
sudo systemctl restart sshd
```

The `--region` matters: the makeway profile defaults to `ap-south-1` while
the platform lives in `us-east-1`, and SSM calls aimed at the wrong region
fail with a misleading `403 UnauthorizedRequest / Forbidden` (the same
signature expired shell-credentials produce — `env | grep ^AWS_` should be
empty when the profile is meant to carry the auth).

`clientspecified` (not `yes`) keeps the client in control of the bind address
and does not open sshd beyond what the security group already restricts.

## 3. Start the tunnel (every dev session)

On the laptop — Windows ships the OpenSSH client, so no install is needed,
and the default key (`~/.ssh/id_ed25519`) is used automatically. The bastion
user on AL2023 is `ec2-user`.

**Default — SSM-brokered SSH** (adds no internet-facing port to the bastion;
two terminals). Terminal 1 forwards the bastion's sshd port to the laptop
over SSM — the same start-session used for the RDS port-forward, pointed at
port 22:

```bash
aws ssm start-session --target <bastion-instance-id> \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["22"],"localPortNumber":["2222"]}' \
  --region us-east-1 --profile makeway
```

Terminal 2 tunnels through it:

```bash
ssh -N -p 2222 -R 0.0.0.0:6443:127.0.0.1:6443 ec2-user@127.0.0.1 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes
```

The `--parameters` JSON is written for bash. In Windows PowerShell 5.1 the
inner double quotes are stripped when the argument reaches the AWS CLI, so
escape them — `'{\"portNumber\":[\"22\"],\"localPortNumber\":[\"2222\"]}'` —
or run the command verbatim from Git Bash.

**Alternative — direct SSH** (needs the `tcp/22` ingress rule from the
operator IP and an EIP, per §1):

```bash
ssh -N -R 0.0.0.0:6443:127.0.0.1:6443 ec2-user@<bastion-public-ip> \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes
```

Flag notes:

- `-N` — no shell, just the forward.
- `-R 0.0.0.0:6443:127.0.0.1:6443` — the reverse bind; the leading `0.0.0.0`
  is only honored because of the `GatewayPorts` setting from step 2.
- `ServerAliveInterval`/`CountMax` — keep the session from idling out behind
  NAT; the SSH process **must keep running**, exactly like the loca.lt
  process it replaces.
- `ExitOnForwardFailure=yes` — if the bind fails (e.g. a stale session still
  holds 6443), the process exits loudly instead of limping on without the
  forward. Rerun the command to recover — no subdomain to re-claim.

## 4. Verify

On the bastion (via the SSM session), the bind must show non-loopback and the
apiserver must answer through it:

```bash
ss -tlnp | grep 6443        # -> sshd LISTEN 0.0.0.0:6443 (127.0.0.1 only => GatewayPorts not in effect)
curl -sk https://<bastion-private-ip>:6443/version   # -> {"major":"1","minor":"..."}
```

Then confirm the registry carries the new endpoint (redacted internal
endpoint — never returns the token):

```bash
curl -H "X-Internal-API-Key: <INTERNAL_API_KEY>" \
  $CONTROL_PLANE_URL/internal/clusters/qa-cluster
# -> {"clusterName":"qa-cluster","environment":"qa",
#     "kubeApiEndpoint":"https://<bastion-private-ip>:6443","hasToken":true,"hasCaCert":false}
```

## 5. Register the endpoint (once — survives every restart)

Same registration contract as the loca.lt flow: re-registering the existing
`clusterName` on the same environment updates endpoint/token/CA in place.

```bash
curl -X POST $CONTROL_PLANE_URL/cluster/register \
  -H "Authorization: Bearer <your user JWT>" -H "Content-Type: application/json" \
  -d '{
        "clusterName": "qa-cluster",
        "kubeApiEndpoint": "https://<bastion-private-ip>:6443",
        "kubeToken": "<makeway-worker token>",
        "kubeCaCert": "",
        "environment": "qa"
      }'
```

Once the `PUT /cluster/{clusterId}` update endpoint is deployed, an endpoint
change can also be applied with a patch that omits the token/CA entirely —
omitted fields keep their stored values.

Keep the Lambda fallback env in sync as in the loca.lt flow: set the
`MAKEWAY_KUBE_API_ENDPOINT` Actions variable to the same
`https://<bastion-private-ip>:6443` and run **deploy-infra**. The registry is
authoritative; the env is only the fallback.

## Security notes

- **The only new inbound surface is 6443, scoped to the workers' security
  group.** The bastion's SG keeps its default-deny posture for everything
  else; with the SSM-brokered SSH variant, no internet-facing port is added
  at all.
- **The bearer token remains the auth boundary** at the apiserver, backed by
  the least-privilege `makeway-worker` RBAC (see
  [workers/step_functions/step_2 - Infra Provisioning/README.md](../workers/step_functions/step_2%20-%20Infra%20Provisioning/README.md)).
- **TLS verification**: with `kubeCaCert` empty the workers run with
  verification disabled (the dev-tunnel convention) — the SSH layer still
  encrypts the leg, and the loca.lt edge is out of the path. To turn
  verification ON, two things must hold together: the workers need the kind
  CA (`kubeCaCert`, base64) *and* the apiserver certificate must cover the
  name they connect to — add the bastion's private IP to the cluster's
  `extraSANs` in the kind config, otherwise hostname checking fails with the
  CA in place.
- Never commit `kubeconfig.yaml` or the worker token — unchanged from the
  loca.lt setup.



## Steps to use bastion as tunnel for cluster

```md
LOCAL — your laptop (Git Bash): edit terraform.tfvars → replace the old line with bastion_ssh_public_key = "ssh-ed25519 AAAA... Kapil@LAPTOP-JJQKJ1VO" (full .pub line)

LOCAL: commit + push the staged fixes (main.tf, variables.tf, deploy-infra.yaml, docs, client.ts).

LOCAL: cd terraform && terraform apply — OR run the deploy-infra workflow on GitHub (same effect; the instance is currently destroyed, so this creates a fresh bastion WITH the key).

LOCAL: get the new instance id + private IP — aws ec2 describe-instances --region us-east-1 --profile makeway --filters Name=tag:Name,Values=makeway-bastion Name=instance-state-name,Values=running --query "Reservations[].Instances[].[InstanceId,PrivateIpAddress]" --output text

LOCAL: aws ssm start-session --target <new-instance-id> --region us-east-1 --profile makeway — this opens a shell INSIDE the bastion; everything you type next runs on the bastion.

INSIDE THE BASTION (the shell from step 5): echo 'GatewayPorts clientspecified' | sudo tee /etc/ssh/sshd_config.d/40-gatewayports.conf && sudo systemctl restart sshd

INSIDE THE BASTION: exit (leave that session open if you like, but the tunnel comes next from your laptop).

LOCAL, Terminal 1: aws ssm start-session --target <new-instance-id> --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["22"],"localPortNumber":["2222"]}' --region us-east-1 --profile makeway

LOCAL, Terminal 2: ssh -N -p 2222 -R 0.0.0.0:6443:127.0.0.1:6443 ec2-user@127.0.0.1 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes

INSIDE THE BASTION (another SSM shell, step 5 again): ss -tlnp | grep 6443 must show 0.0.0.0:6443, then curl -sk https://<private-ip-from-step-4>:6443/version must return JSON.

LOCAL (or me): register — POST /cluster/register, same clusterName, kubeApiEndpoint = https://<private-ip>:6443.

GITHUB — Actions variables: MAKEWAY_KUBE_API_ENDPOINT = https://<private-ip>:6443, then run deploy-infra once more (or with step 3's apply it's already baked).
```