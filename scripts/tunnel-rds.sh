#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# tunnel-rds.sh — Open an SSH tunnel from your laptop to the Makeway RDS
# instance, through the bastion and the EC2 Instance Connect Endpoint (EICE).
#
# RDS is in private subnets with publicly_accessible=false. The only sanctioned
# path from outside the VPC is: laptop -> EICE -> bastion -> RDS:5432.
#
# Usage:
#   scripts/tunnel-rds.sh                 # open tunnel (local:5432 -> RDS:5432)
#   scripts/tunnel-rds.sh --local-port 15432
#   AWS_PROFILE=myprofile scripts/tunnel-rds.sh
#
# While this runs in the foreground, connect to:
#   postgresql://postgres:<db_password>@localhost:5432/makeway
# (i.e. the DATABASE_URL host stays "localhost"). Ctrl-C to close.
#
# No SSH key material needed — the port is brokered by EC2 Instance Connect.
# Requires: aws CLI >= 2.16 with the `ec2-instance-connect` subcommand, and
# credentials that can call ec2-instance-connect + ec2 DescribeInstances.
# ---------------------------------------------------------------------------
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
LOCAL_PORT="${LOCAL_PORT:-5432}"
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
  echo "!! bastion not found. Is the platform deployed? (check: terraform output in terraform/)" >&2
  exit 1
fi
echo ">> bastion instance: ${BASTION_ID}"

# Resolve the RDS endpoint from the platform Terraform state.
echo ">> resolving RDS endpoint from terraform state (terraform/)..."
RDS_HOST="$(cd "$(dirname "$0")/../terraform" && terraform output -raw control_plane_db_endpoint 2>/dev/null || true)"
if [[ -z "$RDS_HOST" || "$RDS_HOST" == "null" || "$RDS_HOST" == "" ]]; then
  echo "!! could not read control_plane_db_endpoint from terraform state." >&2
  echo "   Set RDS_HOST=<endpoint> explicitly and re-run, e.g.:" >&2
  echo "   RDS_HOST=makeway-db.xxxxx.ap-south-1.rds.amazonaws.com scripts/tunnel-rds.sh" >&2
  exit 1
fi
echo ">> rds endpoint: ${RDS_HOST}:${REMOTE_PORT}"

echo ">> opening tunnel (local:${LOCAL_PORT} -> ${RDS_HOST}:${REMOTE_PORT}); Ctrl-C to close..."
exec aws ec2-instance-connect open-tunnel \
  --region "$REGION" \
  --instance-id "$BASTION_ID" \
  --remote-host "$RDS_HOST" \
  --remote-port "$REMOTE_PORT" \
  --local-port "$LOCAL_PORT"