
from pydantic import BaseModel,Field, HttpUrl

from dto.enums.environment import Environment


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
    environment: Environment = Field(
        ...,
        description=(
            "Environment this cluster serves. Must be one of the platform "
            "environments — app creation resolves clusters by this value, so "
            "free-form names would never match."
        ),
        examples=["qa", "uat", "prod"],
    )
    kubeToken: str | None = Field(
        default=None,
        description=(
            "Bearer token for the 'makeway-worker' ServiceAccount on this "
            "cluster. Optional: when empty, the Step-2 worker falls back to "
            "the Lambda environment's KUBE_TOKEN for capabilities on this "
            "cluster."
        ),
    )
    kubeCaCert: str | None = Field(
        default=None,
        description=(
            "Base64 CA bundle of this cluster's exposed apiserver. Empty "
            "disables TLS verification (the pinggy raw-TCP tunnel keeps the "
            "cluster's self-signed cert unmatchable)."
        ),
    )
