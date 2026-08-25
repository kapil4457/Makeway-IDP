"""
Environment-specific constraints for app creation requests.

These constraints are system-defined and imposed on incoming requests.
They define per-environment limits for pods, database capacity, resource quotas,
and limit ranges.

Environments:
  - dev:  Maximum 1 pod per service, max database capacity tier 1
  - uat:  Maximum 3 pods per service, max database capacity tier 2
  - prod: Maximum 5 pods per service, max database capacity tier 4
"""

from dto.enums.environment import Environment

# Per-environment constraint definitions
ENV_CONSTRAINTS = {
    Environment.DEV: {
        "max_pods_per_service": 1,
        "max_database_capacity": 10,
    },
    Environment.UAT: {
        "max_pods_per_service": 3,
        "max_database_capacity": 20,
    },
    Environment.PROD: {
        "max_pods_per_service": 5,
        "max_database_capacity": 40,
    },
}


def get_constraints(env: Environment) -> dict:
    """Get the constraint configuration for a given environment."""
    return ENV_CONSTRAINTS.get(env, ENV_CONSTRAINTS[Environment.DEV])