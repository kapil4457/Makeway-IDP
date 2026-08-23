from sqlmodel import Field, UniqueConstraint
from .shared_audit import SharedAudit
from dto.enums.access_binding_type import AccessBindingStatus

class AccessBinding(SharedAudit, table=True):
    accessBindingId: int = Field(primary_key=True)
    roleArn: str = Field(nullable=False)
    accessType: AccessBindingStatus = Field(nullable=False)

    capabilityId: int = Field(nullable=False, foreign_key="capability.capabilityId", index=True)
    namespaceId: int = Field(nullable=False, foreign_key="namespace.namespaceId", index=True)
    serviceId: int = Field(nullable=False, foreign_key="service.svcId", index=True)

    __table_args__ = (
        UniqueConstraint("capabilityId", "serviceId", "namespaceId", name="uq_access_binding_cap_svc_ns"),
    )