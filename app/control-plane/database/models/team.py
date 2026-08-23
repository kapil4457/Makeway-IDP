from sqlmodel import Field

from .shared_audit import SharedAudit


class Team(SharedAudit, table=True):
    teamId: int = Field(primary_key=True)
    teamName: str = Field(unique=True)