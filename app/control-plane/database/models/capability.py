from sqlmodel import Field, UniqueConstraint
from .shared_audit import SharedAudit
from dto.enums.capability_status import CapabilityStatus

class Capability(SharedAudit, table=True):
    capabilityId: int = Field(primary_key=True)
    capabilityType: str = Field(nullable=False)
    status: CapabilityStatus = Field(default=CapabilityStatus.PENDING, nullable=False)
    errorMessage: str = Field(default=None, nullable=True)
    
    serviceId: int = Field(nullable=False, foreign_key="service.svcId", index=True)
    envId: int = Field(nullable=False,foreign_key="environment.envId", index=True)