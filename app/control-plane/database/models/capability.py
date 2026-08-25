from sqlmodel import Field, Column
from .shared_audit import SharedAudit
from sqlalchemy.dialects.postgresql import JSONB
from dto.enums.capability_status import CapabilityStatus

class Capability(SharedAudit, table=True):
    capabilityId: int = Field(primary_key=True)
    capabilityType: str = Field(nullable=False)
    status: CapabilityStatus = Field(default=CapabilityStatus.PENDING, nullable=False)
    errorMessage: str = Field(default=None, nullable=True)
