from datetime import datetime, timezone
from sqlmodel import Field, SQLModel

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SharedAudit(SQLModel):
    createdBy: str = Field(default="SYSTEM",nullable=False)
    createdAt: datetime = Field(default_factory=utc_now)
    modifiedBy: str =  Field(default="SYSTEM",nullable=False)
    modifiedAt: datetime = Field(
        default_factory=utc_now,
        sa_column_kwargs={"onupdate": utc_now},
    )