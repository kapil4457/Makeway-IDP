from sqlmodel import Field, UniqueConstraint

from .shared_audit import SharedAudit
from dto.enums.namespace_status import NamespaceStatus

class Namespace(SharedAudit, table=True):
    namespaceId: int = Field(primary_key=True)
    k8sNamespaceName: str = Field(nullable=False)
    status: NamespaceStatus = Field(default=NamespaceStatus.PENDING, nullable=False)

    serviceId: int = Field(nullable=False, foreign_key="service.svcId", index=True)
    envId: int = Field(nullable=False, foreign_key="environment.envId", index=True)
    clusterId: int = Field(nullable=False, foreign_key="cluster.clusterId", index=True)
    
    __table_args__ = (
            UniqueConstraint("serviceId", "envId", name="uq_namespace_service_env"),
        )