#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# tunnel-rds.sh — Open a tunnel from your laptop to the Makeway RDS instance
# ---------------------------------------------------------------------------
set -euo pipefail

# Support inline positional parameter flags (e.g., --local-port 15432)
while [[ $# -gt 0 ]]; do
  case $1 in
    --local-port)
      LOCAL_PORT="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

REGION="${AWS_REGION:-ap-south-1}"
LOCAL_PORT="${LOCAL_PORT:-5432}"
# FIXED: Re-added variable expansion check & hardcoded fallback address
REMOTE_HOST="${RDS_ENDPOINT:-makeway-db.c388w48wc3il.ap-south-1.rds.amazonaws.com}"            
REMOTE_PORT="${REMOTE_PORT:-5432}"
BASTION_TAG="makeway-bastion"

# Resolve the bastion instance id by Name tag.
echo ">> looking up bastion instance (tag:Name=${BASTION_TAG}, region=${REGION})...."
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

# Resolve the RDS endpoint from state if the hardcoded default or override isn't explicitly set
if [[ -z "$REMOTE_HOST" || "$REMOTE_HOST" == "null" ]]; then
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

# FIXED: Wrapped parameter variables cleanly into JSON array formats for SSM
exec aws ssm start-session \
  --region "$REGION" \
  --target "$BASTION_ID" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"${REMOTE_HOST}\"],\"portNumber\":[\"${REMOTE_PORT}\"],\"localPortNumber\":[\"${LOCAL_PORT}\"]}"
