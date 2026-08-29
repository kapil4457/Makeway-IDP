#!/bin/bash
# Boot script for the ECS-optimized container instances.
# Joins the instance to the Makeway ECS cluster and enables spot-instance
# draining so ECS can move tasks off a rebalancing spot instance gracefully.
# Installs the EC2 Instance Connect agent so one-time SSH keys injected via
# the Instance Connect Endpoint land in authorized_keys.
set -euxo pipefail

# The AL2 ECS-optimized image doesn't ship the Instance Connect agent.
yum install -y ec2-instance-connect || true

cat <<'EOF' >> /etc/ecs/ecs.config
ECS_CLUSTER=${cluster_name}
ECS_ENABLE_SPOT_INSTANCE_DRAINING=true
EOF
