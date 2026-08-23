from sqlmodel import Column, Column, Field
from .shared_audit import SharedAudit
from dto.enums.request_status import RequestStatus
from dto.enums.request_type import RequestType
from sqlalchemy.dialects.postgresql import JSONB

class Request(SharedAudit, table=True):
    requestId: int = Field(primary_key=True)
    idempotencyKey: str = Field(unique=True, nullable=False)
    requestType: RequestType = Field(nullable=False)
    requestStatus: RequestStatus = Field(nullable=False)
    rawRequest: dict = Field(default=None, sa_column=Column(JSONB, nullable=True))
    
    appId: int = Field(default=None, foreign_key="app.appId", index=True, nullable=True)