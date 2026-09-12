from sqlmodel import Field

from .shared_audit import SharedAudit


class Cluster(SharedAudit, table=True):
    clusterId: int | None = Field(default=None, primary_key=True)
    clusterName: str = Field(unique=True, nullable=False, max_length=63 )
    kubeApiEndpoint: str = Field(nullable=False)
    environment: str = Field(nullable=False)
    # Cluster-scoped worker credentials. Optional: when a row has none, the
    # Step-2 worker falls back to its Lambda env KUBE_TOKEN / KUBE_CA_CERT.
    # kubeCaCert is the base64 apiserver bundle; empty disables TLS verification
    # (pinggy raw-TCP tunnel keeps the cluster's self-signed cert unmatchable).
    kubeToken: str | None = Field(default=None, nullable=True)
    kubeCaCert: str | None = Field(default=None, nullable=True)
    