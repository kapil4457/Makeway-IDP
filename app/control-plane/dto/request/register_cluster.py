
from pydantic import BaseModel,Field, HttpUrl


class ClusterRegisterRequest(BaseModel):
    """Request payload for cluster registration."""

    clusterName: str = Field(
        ...,
        description="Desired cluster configuration.",
        examples=["my-cluster"],
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"
    )
    kubeApiEndpoint: HttpUrl = Field(
        ...,
        description="The API endpoint for the Kubernetes cluster.",
        examples=["https://kubernetes.default.svc"]

    )
