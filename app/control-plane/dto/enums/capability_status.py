from enum import Enum

class CapabilityStatus(str, Enum):
    """Status of a capability in the Makeway platform."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIALLY_FAILED = "partially_failed"