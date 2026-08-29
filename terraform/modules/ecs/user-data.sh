#!/bin/bash
# Boot script for the ECS-optimized container instances.
# Joins the instance to the Makeway ECS cluster and enables spot-instance
# draining so ECS can move tasks off a rebalancing spot instance gracefully.
set -euxo pipefail

cat <<'EOF' >> /etc/ecs/ecs.config
ECS_CLUSTER=${cluster_name}
ECS_ENABLE_SPOT_INSTANCE_DRAINING=true
EOF
