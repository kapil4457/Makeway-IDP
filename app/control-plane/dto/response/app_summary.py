from datetime import datetime

from pydantic import BaseModel, Field


class AppSummaryResponse(BaseModel):
    """List-row shape for ``GET /app`` — the dashboard's landing grid.

    One row per app owned by one of the caller's active teams, mirroring the
    camelCase style of ``AppStatusResponse``. Deliberately lighter than the
    status snapshot: identification + ownership + audit only.
    """

    appId: int = Field(...)
    appName: str = Field(...)
    appRepoUrl: str | None = Field(
        default=None,
        description="GitHub repository Step-1 created, once reconciled.",
    )
    gitOpsPath: str | None = Field(
        default=None,
        description="Platform-repo path holding this app's GitOps tree.",
    )
    teamId: int = Field(...)
    teamName: str | None = Field(
        default=None,
        description="Owning team's name, resolved from teamId.",
    )
    createdBy: str = Field(...)
    createdAt: datetime = Field(...)
    modifiedBy: str = Field(...)
    modifiedAt: datetime = Field(...)