from sqlmodel import Field

from .shared_audit import SharedAudit


class App(SharedAudit, table=True):
    appId: int = Field(primary_key=True)
    appName: str = Field(unique=True)
    appRepoUrl: str = Field(default=None, nullable=True)
    gitOpsRepoUrl: str = Field(default=None, nullable=True)
    teamId: int = Field(nullable=False, foreign_key="team.teamId", index=True)
    