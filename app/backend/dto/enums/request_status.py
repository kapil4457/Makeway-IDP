from enum import Enum

class RequestStatus(str, Enum):
    """Status of a request in the Makeway platform."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PROVISIONED = "provisioned"
    FAILED = "failed"