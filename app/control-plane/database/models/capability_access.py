from sqlmodel import Field, Column
from .shared_audit import SharedAudit
from sqlalchemy.dialects.postgresql import JSONB
from dto.enums.capability_status import CapabilityStatus

class CapabilityAccess(SharedAudit, table=True):
    capabilityAccessId: int =  Field(primary_key=True) 
    capabilityId: int = Field(nullable=False, foreign_key="capability.capabilityId", index=True)
    serviceId: int = Field(nullable=False, foreign_key="service.svcId", index=True)
    