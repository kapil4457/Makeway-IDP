#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# tunnel-rds.sh — Open a tunnel from your laptop to the Makeway RDS instance
# through the bastion, using SSM Session Manager port-forwarding.
#
# RDS is in private subnets with publicly_accessible=false. The sanctioned
# path from outside the VPC is: laptop -> SSM -> bastion -> RDS:5432.
# EC2 Instance Connect Endpoint is not available in ap-south-1, and the
# bastion already carries AmazonSSMManagedInstanceCore, so SSM is the jump.
#
# Usage:
#   scripts/tunnel-rds.sh                 # open tunnel (local:5432 -> RDS:5432)
#   scripts/tunnel-rds.sh --local-port 15432
#   AWS_PROFILE=myprofile scripts/tunnel-rds.sh
#
# While this runs in the foreground, connect to:
#   postgresql://postgres:<db_password>@localhost:5432/makeway
# (the DATABASE_URL host stays "localhost"). Ctrl-C to close.
#
# No SSH key material needed — SSM brokers the session. Requires:
#   - AWS CLI with the `ssm` subcommand (>= 2.x)
#   - AWS credentials that can call ssm:StartSession on the bastion, plus
#     ec2:DescribeInstances (to resolve the bastion id).
# ---------------------------------------------------------------------------
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
LOCAL_PORT="${LOCAL_PORT:-5432}"
REMOTE_HOST="${RDS_ENDPOINT:-}"            # set manually to skip terraform lookup
REMOTE_PORT="${REMOTE_PORT:-5432}"
BASTION_TAG="makeway-bastion"

# Resolve the bastion instance id by Name tag.
echo ">> looking up bastion instance (tag:Name=${BASTION_TAG}, region=${REGION})..."
BASTION_ID="$(aws ec2 describe-instances \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=${BASTION_TAG}" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text)"
if [[ -z "$BASTION_ID" || "$BASTION_ID" == "None" ]]; then
  echo "!! bastion not found. Is the platform deployed? (check 'terraform output' in terraform/)" >&2
  exit 1
fi
echo ">> bastion instance: ${BASTION_ID}"

# Resolve the RDS endpoint (host) — from terraform state, or RDS_ENDPOINT env.
if [[ -z "$REMOTE_HOST" ]]; then
  echo ">> resolving RDS endpoint from terraform state (terraform/)..."
  REMOTE_HOST="$(cd "$(dirname "$0")/../terraform" && terraform output -raw control_plane_db_endpoint 2>/dev/null || true)"
  if [[ -z "$REMOTE_HOST" || "$REMOTE_HOST" == "null" || "$REMOTE_HOST" == "<nil>" ]]; then
    echo "!! could not read control_plane_db_endpoint from terraform state." >&2
    echo "   Set RDS_ENDPOINT=<endpoint-host> explicitly and re-run, e.g.:" >&2
    echo "   RDS_ENDPOINT=makeway-db.xxxxx.ap-south-1.rds.amazonaws.com scripts/tunnel-rds.sh" >&2
    exit 1
  fi
fi
echo ">> rds endpoint: ${REMOTE_HOST}:${REMOTE_PORT}"

echo ">> starting SSM session manager port-forward (local:${LOCAL_PORT} -> ${REMOTE_HOST}:${REMOTE_PORT}); Ctrl-C to close..."
exec aws ssm start-session \
  --region "$REGION" \
  --target "$BASTION_ID" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "host=${REMOTE_HOST},portNumber=${REMOTE_PORT},localPortNumber=${LOCAL_PORT}"