from pydantic import BaseModel, Field


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
    gitOpsRepoUrl: str | None = Field(
        default=None,
        description="URL of the app's gitops repo.",
        examples=["https://github.com/kapil4457/order-service-gitops"],
    )
    serviceRepoPaths: list[InternalServiceRepoPath] | None = Field(
        default=None,
        description="Per-service folder paths inside the services repo.",
    )