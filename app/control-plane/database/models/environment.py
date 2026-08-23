from sqlmodel import Field, UniqueConstraint

from .shared_audit import SharedAudit


class Environment(SharedAudit, table=True):
    envId: int = Field(primary_key=True)
    envName: str = Field(nullable=False)

    clusterId: int = Field(nullable=False, foreign_key="cluster.clusterId", index=True)
    appId: int = Field(nullable=False, foreign_key="app.appId", index=True)

    __table_args__ = (
            UniqueConstraint("appId", "envName", name="uq_environment_app_env"),
        )