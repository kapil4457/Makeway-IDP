from sqlmodel import Field, UniqueConstraint
from .shared_audit import SharedAudit
from dto.enums.service_type import ServiceType

class Service(SharedAudit, table=True):
    svcId: int = Field(primary_key=True)
    svcName: str = Field(nullable=False)
    serviceType: ServiceType = Field(nullable=False)
    repoPath: str = Field(default=None, nullable=True)
    clusterId: int = Field(nullable=False, foreign_key="cluster.clusterId", index=True) 
    appId: int = Field(nullable=False, foreign_key="app.appId", index=True)

    __table_args__ = (
            UniqueConstraint("appId", "svcName", "clusterId", name="uq_service_app_svc_cluster"),
        )