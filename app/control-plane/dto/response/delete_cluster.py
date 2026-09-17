from pydantic import BaseModel, Field


class ClusterDeleteResponse(BaseModel):
    """Response for ``DELETE /cluster/{cluster_id}`` — the deregistered cluster."""

    clusterName: str = Field(...)
    environment: str = Field(
        ...,
        description="The environment this cluster served; it is now free for re-registration.",
    )
