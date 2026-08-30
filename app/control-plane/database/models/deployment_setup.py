from sqlmodel import Field, UniqueConstraint
from .shared_audit import SharedAudit
from datetime import datetime


class DeploymentSetup(SharedAudit, table=True):
    deploymentSetupId: int = Field(primary_key=True)
    status: str = Field(nullable=False)
    argocdAppName: str | None = Field(default=None, nullable=True)
    lastSyncedAt: datetime | None = Field(default=None, nullable=True)
    errorMessage: str | None = Field(default=None, nullable=True)

    serviceId: int = Field(nullable=False, foreign_key="service.svcId", index=True)