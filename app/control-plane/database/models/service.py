from sqlmodel import Field, UniqueConstraint
from .shared_audit import SharedAudit
from dto.enums.service_type import ServiceType

class Service(SharedAudit, table=True):
    svcId: int = Field(primary_key=True)
    svcName: str = Field(nullable=False)
    serviceType: ServiceType = Field(nullable=False)
    repoPath: str = Field(default=None, nullable=True)

    appId: int = Field(nullable=False, foreign_key="app.appId", index=True)

    __table_args__ = (
            UniqueConstraint("appId", "svcName", name="uq_service_app_svc"),
        )