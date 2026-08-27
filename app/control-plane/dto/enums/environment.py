from enum import Enum


class Environment(str, Enum):
    """Deployment environments managed by the Makeway platform."""

    DEV = "dev"
    QA = "qa"
    UAT = "uat"
    PROD = "prod"
