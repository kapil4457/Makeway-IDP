from sqlmodel import Field

from .shared_audit import SharedAudit


class User(SharedAudit, table=True):
    userId: int = Field(primary_key=True)
    email: str = Field(nullable=False, unique=True)
    password: str = Field(nullable=False)