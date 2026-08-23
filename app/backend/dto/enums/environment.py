from enum import Enum


class Environment(str, Enum):
    """Deployment environments managed by the Makeway platform."""

    DEV = "dev"
    UAT = "uat"
    PROD = "prod"
