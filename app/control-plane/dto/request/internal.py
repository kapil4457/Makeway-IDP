from datetime import datetime
from pydantic import BaseModel, Field
from dto.enums.capability_status import CapabilityStatus

class InternalCapabilityOutput(BaseModel):
    """Per-capability result reported back by the provision-infra worker.

    The Step-2 (Crossplane) worker applies a Claim per capability and reports
    one of these per capability: the connection outputs Crossplane wrote into
    the Claim's connection Secret (endpoint/port/ARN …) and the Secrets Manager
    ARN the credentials were mirrored into. The control plane persists them
    into ``InfraRequirement.outputRef`` / ``InfraRequirement.secretRef`` and
    rolls ``Capability.status`` up.
    """

    capabilityId: int = Field(
        ...,
        description="Primary key of the capability row this report concerns.",
        examples=[201],
    )
    status: CapabilityStatus = Field(
        ...,
        description="Per-capability status — one of the ``CapabilityStatus`` wire "
        "values (success / failed / partially_failed).",
        examples=["success"],
    )
    outputRef: dict | None = Field(
        default=None,
        description="Connection outputs Crossplane wrote into the Claim's "
        "connection Secret (e.g. ``{endpoint, port, databaseName}`` for RDS, "
        "``{bucketName, region, arn}`` for S3). Falls through to "
        "``InfraRequirement.outputRef``.",
    )
    secretRef: str | None = Field(
        default=None,
        description="ARN of the AWS Secrets Manager secret the credentials were "
        "mirrored into (``InfraRequirement.secretRef``). Never the value itself.",
        examples=["arn:aws:secretsmanager:ap-south-1:123456789012:secret:order-service-qa-orders"],
    )
    errorMessage: str | None = Field(
        default=None,
        description="Failure detail when ``status`` is ``failed``/``partially_failed``.",
    )


class InternalServiceRepoPath(BaseModel):
    """Which folder a service was scaffolded into inside the services repo."""

    svcId: int = Field(
        ...,
        description="Primary key of the service row to update.",
        examples=[101],
    )
    repoPath: str | None = Field(
        default=None,
        description="Folder path of the service inside the services monorepo "
        "(environment suffix stripped, e.g. ``orders-api``).",
        examples=["orders-api"],
    )


class InternalStatusUpdateRequest(BaseModel):
    """Status/URL callback received from state-machine workers.

    Field names are intentionally *camelCase*: they travel verbatim in the JSON
    body produced by workers (Lambda handlers publish ``jobId``, ``appRepoUrl``,
    ``serviceRepoPaths`` …), so aliases are required to map them onto SQLModel
    snake_case columns.
    """

    jobId: int | None = Field(
        default=None,
        description="Job whose status is being reported.",
        examples=[501],
    )
    step: str | None = Field(
        default=None,
        description="Job step the worker belongs to (e.g. ``create_project``).",
        examples=["create_project"],
    )
    status: str = Field(
        ...,
        description="New job status — one of the ``JobStatus`` wire values.",
        examples=["success"],
    )
    executionArn: str | None = Field(
        default=None,
        description="Step Functions execution ARN to persist on the job.",
        examples=["arn:aws:states:ap-south-1:123456789012:execution:makeway-app-creation:a1b2c3"],
    )
    error: str | None = Field(
        default=None,
        description="Failure detail when ``status`` is ``failed`` (worker truncates).",
        examples=["github POST /orgs/kapil4457/repos -> HTTP 422"],
    )
    appRepoUrl: str | None = Field(
        default=None,
        description="URL of the app's services monorepo.",
        examples=["https://github.com/kapil4457/order-service"],
    )
    gitOpsPath: str | None = Field(
        default=None,
        description="Folder path of the app's gitops config inside the platform "
        "repo (e.g. ``argocd/apps/order-service/``). The platform repo URL "
        "itself is constant (core.config.GITOPS_REPO_URL) and not stored "
        "per row.",
        examples=["argocd/apps/order-service/"],
    )
    serviceRepoPaths: list[InternalServiceRepoPath] | None = Field(
        default=None,
        description="Per-service folder paths inside the services repo.",
    )
    capabilities: list[InternalCapabilityOutput] | None = Field(
        default=None,
        description="Per-capability provisioning results from the Step-2 "
        "(Crossplane provision-infra) worker. Absent for earlier steps.",
    )


class InternalDeploymentSetupReport(BaseModel):
    """ArgoCD rollout state for a service, reported by the deploy reporter.

    Fields are camelCase to travel verbatim in the JSON body a Lambda produces
    (like the other internal DTOs) and map onto the snake_case columns of the
    ``DeploymentSetup`` model. The reporter would typically derive this from an
    ArgoCD Application's health/sync status; the control plane only persists the
    last-known state, so service health on ``GET /app/.../status`` stays honest
    ``unknown`` until the first report lands.
    """

    svcId: int = Field(
        ...,
        description="Primary key of the service this deployment belongs to.",
        examples=[101],
    )
    status: str = Field(
        ...,
        description="ArgoCD sync/rollout status of the service's Application "
        "(e.g. ``success``, ``synced``, ``failed``). Persisted verbatim on "
        "``DeploymentSetup.status``.",
        examples=["synced"],
    )
    argocdAppName: str | None = Field(
        default=None,
        description="Name of the ArgoCD Application managing this service's "
        "Deployment (``DeploymentSetup.argocdAppName``).",
        examples=["orders-api-qa"],
    )
    lastSyncedAt: datetime | None = Field(
        default=None,
        description="When ArgoCD last reported a successful sync. Persisted on "
        "``DeploymentSetup.lastSyncedAt`` and surfaced as the status snapshot's "
        "``lastUpdatedAt``.",
    )
    errorMessage: str | None = Field(
        default=None,
        description="Failure detail when the sync/rollout failed. Surfaces as "
        "the service health error and rolls into the env-level ``errors`` list.",
        examples=["ArgoCD sync failed: unable to reach image tag"],
    )


class InternalDeploymentGroupResponse(BaseModel):
    """The deployment group behind one ``(app, env)`` ArgoCD Application.

    The ArgoCD ApplicationSet creates one Application per ``(app, env)``
    overlay, and the Application is what the health reporter observes. This
    response tells the reporter which services roll out through that
    Application — the ``svcIds`` it then reports ``DeploymentSetup`` rows
    against. An env with no cluster yet returns an honest empty ``svcIds``.
    """

    env: str = Field(
        ...,
        description="Environment the group belongs to (qa/uat/prod).",
        examples=["qa"],
    )
    svcIds: list[int] = Field(
        ...,
        description="Services in the app that roll out through the ``(app, env)`` "
        "ArgoCD Application (empty when the cluster for that env doesn't exist).",
        examples=[[11, 12]],
    )