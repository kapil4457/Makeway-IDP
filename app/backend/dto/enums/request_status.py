from enum import Enum

class RequestStatus(str, Enum):
    """Status of a request in the Forge platform."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PROVISIONED = "provisioned"
    FAILED = "failed"