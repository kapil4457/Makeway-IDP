from enum import Enum

class DeploymentStatus(str, Enum):
    """Status of a deployment in the Makeway platform."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"