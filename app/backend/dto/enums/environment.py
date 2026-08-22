from enum import Enum


class Environment(str, Enum):
    """Deployment environments managed by the Forge platform."""

    DEV = "dev"
    UAT = "uat"
    PROD = "prod"
