from sqlmodel import Field, UniqueConstraint
from .shared_audit import SharedAudit
from datetime import datetime


class DeploymentSetup(SharedAudit, table=True):
    deploymentSetupId: int = Field(primary_key=True)
    status: str = Field(nullable=False)
    argocdAppName: str = Field(default=None)
    lastSyncedAt: datetime = Field(default=None)
    errorMessage: str = Field(default=None)
    
    serviceId: int = Field(nullable=False, foreign_key="service.svcId", index=True)
    envId: int = Field(nullable=False, foreign_key="environment.envId", index=True)

    __table_args__ = (
            UniqueConstraint("serviceId", "envId", name="uq_deployment_setup_service_env"),
        )