from datetime import datetime

from pydantic import BaseModel, Field


class ClusterSummaryResponse(BaseModel):
    """List-row shape for ``GET /cluster``.

    Credential **presence only** — ``kubeToken``/``kubeCaCert`` values never
    leave the database (mirroring the internal redacted-cluster contract);
    the UI renders check/dash badges from these booleans.
    """

    clusterId: int = Field(...)
    clusterName: str = Field(...)
    kubeApiEndpoint: str = Field(
        ...,
        description="Kubernetes API endpoint the Step-2 worker talks to.",
    )
    environment: str = Field(
        ...,
        description="Platform environment this cluster serves (qa/uat/prod).",
    )
    hasToken: bool = Field(
        ...,
        description="Whether a worker token is persisted for this cluster.",
    )
    hasCaCert: bool = Field(
        ...,
        description="Whether a base64 CA bundle is persisted for this cluster.",
    )
    createdBy: str = Field(...)
    createdAt: datetime = Field(...)
    modifiedBy: str = Field(...)
    modifiedAt: datetime = Field(...)