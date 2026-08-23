from pydantic import BaseModel, Field


class ClusterRegisterResponse(BaseModel):
    """Acknowledgement returned when a cluster registration request is accepted."""
    
    message: str = Field(
        ...,
        description="Human-readable status message.",
        examples=["Cluster registration requested"],
    )
    cluster_name: str = Field(
        ...,
        description="Name of the cluster that was requested.",
        examples=["cluster-1"],
    )