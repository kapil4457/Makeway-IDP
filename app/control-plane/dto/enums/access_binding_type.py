from enum import Enum

class AccessBindingStatus(str, Enum):
    """Status of an access binding in the Makeway platform."""

    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"