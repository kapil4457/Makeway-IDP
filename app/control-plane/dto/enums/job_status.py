from enum import Enum

class JobStatus(str, Enum):
    """Status of a job in the Makeway platform."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"