"""Response schema for ``GET /app/{app_name}/status``.

Returns a per-environment state snapshot of an app: the services running in
each env, the capabilities bound to them, the connectivity edges in between,
and any errors recorded at each level.

``dataSource`` matters here: status fields that come from the persisted
reconcile state (job/capability callbacks) are marked ``persisted``, while a
``realtime`` source means a live check (ArgoCD health, readiness probe) filled
the value. An aggregate endpoint should never quietly mix the two — the UI
can render ``persisted`` values as "last known" and ``realtime`` as green.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from dto.enums.connectivity_status import ConnectivityStatus
from dto.enums.service_health import ServiceHealth


DataSource = Literal["persisted", "realtime"]


class ClusterStatus(BaseModel):
    clusterId: int = Field(...)
    clusterName: str = Field(...)
    environment: str = Field(...)


class DeploymentStatusInfo(BaseModel):
    """Persisted ArgoCD/rollout state for a service's most recent deployment."""

    status: str | None = Field(
        default=None,
        description="DeploymentSetup.status — the last-driven rollout state.",
    )
    argocdAppName: str | None = Field(
        default=None,
        description="ArgoCD Application that reconciles this service.",
    )
    lastSyncedAt: datetime | None = Field(
        default=None,
        description="When ArgoCD last synced the desired git state.",
    )
    errorMessage: str | None = Field(
        default=None,
        description="Rollout-level failure detail, if any.",
    )


class ServiceStatus(BaseModel):
    svcId: int = Field(...)
    svcName: str = Field(...)
    serviceType: str = Field(...)
    health: ServiceHealth = Field(
        default=ServiceHealth.UNKNOWN,
        description="Derived runtime health of the service in this environment.",
    )
    healthSource: DataSource = Field(
        default="persisted",
        description="Where ``health`` came from — persisted state or a live check.",
    )
    lastUpdatedAt: datetime | None = Field(
        default=None,
        description="When the health value was last refreshed (None while untouched).",
    )
    deployment: DeploymentStatusInfo | None = Field(
        default=None,
        description="The persisted rollout state behind ``health``, when known.",
    )
    error: str | None = Field(
        default=None,
        description="Service-level error (rollout failure), if any.",
    )


class InfraStatus(BaseModel):
    """Provisioned-state details returned by the Step-2 Crossplane worker."""

    config: dict | None = Field(
        default=None,
        description="Desired config of the capability (from InfraRequirement).",
    )
    outputRef: dict | None = Field(
        default=None,
        description="Connection outputs (endpoint/port/ARN…) mirrored from the Claim.",
    )
    secretRef: str | None = Field(
        default=None,
        description="Secrets Manager ARN the credentials were mirrored into.",
    )


class CapabilityStatusInfo(BaseModel):
    capabilityId: int = Field(...)
    capabilityType: str = Field(...)
    name: str | None = Field(
        default=None,
        description="Display name of the capability resource (e.g. the DB name), "
        "derived from its config when one exists.",
    )
    status: str = Field(
        ...,
        description="Reconcile status — one of the ``CapabilityStatus`` wire values.",
    )
    statusSource: DataSource = Field(
        default="persisted",
        description="Where the capability status came from.",
    )
    infra: InfraStatus | None = Field(
        default=None,
        description="Provisioned-state details for this capability.",
    )
    error: str | None = Field(
        default=None,
        description="Capability-level error, if any.",
    )


class ConnectivityStatusInfo(BaseModel):
    """The edge between one service and one capability in the same env."""

    serviceSvcId: int = Field(...)
    capabilityId: int = Field(...)
    accessConfigured: bool = Field(
        ...,
        description="A CapabilityAccess binding grants this service the capability.",
    )
    status: ConnectivityStatus = Field(
        default=ConnectivityStatus.UNKNOWN,
        description="Derived state of the edge (intent present vs. actually healthy).",
    )
    source: DataSource = Field(
        default="persisted",
        description="Where the edge state came from — persisted binding or a live connectivity probe.",
    )
    error: str | None = Field(
        default=None,
        description="Binding-level error, if any (e.g. a failed NetworkPolicy).",
    )


class EnvStatus(BaseModel):
    env: str = Field(...)
    cluster: ClusterStatus = Field(...)
    services: list[ServiceStatus] = Field(default_factory=list)
    capabilities: list[CapabilityStatusInfo] = Field(default_factory=list)
    connectivity: list[ConnectivityStatusInfo] = Field(default_factory=list)
    errors: list[str] = Field(
        default_factory=list,
        description="Every error recorded at any level inside this environment.",
    )


class RequestStatusBrief(BaseModel):
    requestId: int = Field(...)
    requestStatus: str = Field(...)
    jobId: int | None = Field(default=None)
    jobStep: str | None = Field(default=None)
    jobStatus: str | None = Field(default=None)
    executionArn: str | None = Field(default=None)
    error: str | None = Field(
        default=None,
        description="Job-level error detail, if the creation flow failed.",
    )


class AppStatusResponse(BaseModel):
    appId: int = Field(...)
    appName: str = Field(...)
    teamName: str | None = Field(default=None)
    appRepoUrl: str | None = Field(default=None)
    gitOpsPath: str | None = Field(default=None)
    request: RequestStatusBrief | None = Field(
        default=None,
        description="The latest create-app request and its job, if one exists.",
    )
    envStatuses: list[EnvStatus] = Field(default_factory=list)