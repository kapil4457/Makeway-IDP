from sqlmodel import Field
from .shared_audit import SharedAudit
from dto.enums.job_step import JobStep
from dto.enums.job_status import JobStatus

class Job(SharedAudit, table=True):
    jobId: int = Field(primary_key=True)
    step: JobStep = Field(nullable=False)
    status: JobStatus = Field(nullable=False)
    stepFunctionExecutionArn: str = Field(default=None, nullable=True)
    errorDetail: str = Field(default=None, nullable=True)
    
    requestId: int = Field(foreign_key="request.requestId", index=True)
    capabilityId: int = Field(default=None, foreign_key="capability.capabilityId", index=True, nullable=True)
    deploymentSetupId: int = Field(default=None, foreign_key="deploymentsetup.deploymentSetupId", index=True, nullable=True)