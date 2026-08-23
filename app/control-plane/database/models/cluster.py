from sqlmodel import Field

from .shared_audit import SharedAudit


class Cluster(SharedAudit, table=True):
    clusterId: int | None = Field(default=None, primary_key=True)
    clusterName: str = Field(unique=True, nullable=False, max_length=63 )
    kubeApiEndpoint: str = Field(nullable=False)
    