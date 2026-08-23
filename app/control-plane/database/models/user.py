from sqlmodel import Field
from uuid import UUID, uuid4
from .shared_audit import SharedAudit


class User(SharedAudit, table=True):
    userId: UUID | None = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(nullable=False, unique=True, max_length=320)
    passwordHash: str = Field(nullable=False)