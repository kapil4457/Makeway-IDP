from enum import Enum

class NamespaceStatus(str, Enum):
    """Status of a namespace in the Makeway platform."""
    
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"