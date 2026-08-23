from sqlmodel import Field

from .shared_audit import SharedAudit


class Cluster(SharedAudit, table=True):
    clusterId: int = Field(primary_key=True)
    clusterName: str = Field(unique=True)
    kubeApiEndpoint: str = Field(default=None, nullable=True)
    