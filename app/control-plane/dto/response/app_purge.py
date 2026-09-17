from pydantic import BaseModel, Field


class AppPurgeResponse(BaseModel):
    """Response for ``DELETE /app/{app_name}`` — the synchronous record purge.

    Counts are per table: rows hard-deleted so the app can be re-created from
    scratch (``appName`` is unique). The services repository on GitHub is
    deliberately kept — record cleanup, not repo teardown.
    """

    appName: str = Field(...)
    purged: dict[str, int] = Field(
        ...,
        description="Rows deleted per table (jobs, requests, app).",
    )
