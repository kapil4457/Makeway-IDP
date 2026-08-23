from sqlmodel import Column, Field
from .shared_audit import SharedAudit
from sqlalchemy.dialects.postgresql import JSONB


class InfraRequirement(SharedAudit, table=True):
    infraRequirementId: int = Field(primary_key=True)
    config: dict = Field(default=None, sa_column=Column(JSONB, nullable=True))
    secretRef: str = Field(default=None, nullable=True)
    outputRef: dict = Field(default=None,sa_column=Column(JSONB, nullable=True))
    errorMessage: str = Field(default=None, nullable=True)
    
    capabilityId: int = Field(nullable=False, foreign_key="capability.capabilityId", index=True)