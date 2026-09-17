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
- `aws_key_pair.bastion` — created once `bastion_ssh_public_key_path` points
  at a public key. Where the value comes from depends on who applies:

  ```hcl
  # local apply — terraform/terraform.tfvars (never committed)
  bastion_ssh_public_key_path = "C:/Users/Kapil/.ssh/id_ed25519.pub"

  # CI apply (deploy-infra) — repo Actions variable (an SSH *public* key is
  # not a secret; it is safe as a plain Actions variable)
  #   MAKEWAY_BASTION_SSH_PUBLIC_KEY = ssh-ed25519 AAAA... Kapil@LAPTOP-...
  ```

  An empty value silently skips the key pair (the resource is `count`-gated)
  — a CI-only apply without the variable deploys a bastion the SSH leg can't
  authenticate to.

The key attaches to the instance as an in-place update — no replacement.
Direct-SSH setups (option A in §3) additionally need ingress `tcp/22` from
the operator's IP and an EIP for a stable target; the SSM-brokered default
needs neither. The **private** IP — what the workers and the cluster
registry use — is stable for the instance's lifetime either way.

## 2. One-time sshd config on the bastion

By default sshd binds `-R` forwards to loopback only; the workers need
`0.0.0.0:6443`. Open an SSM session and set `GatewayPorts`:

```bash
aws ssm start-session --target <bastion-instance-id>

# on the bastion:
echo 'GatewayPorts clientspecified' | sudo tee /etc/ssh/sshd_config.d/40-gatewayports.conf
sudo systemctl restart sshd
```

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
  --parameters '{"portNumber":["22"],"localPortNumber":["2222"]}'
```

Terminal 2 tunnels through it:

```bash
ssh -N -p 2222 -R 0.0.0.0:6443:127.0.0.1:6443 ec2-user@127.0.0.1 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes
```

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
