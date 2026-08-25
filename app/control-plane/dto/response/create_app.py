from pydantic import BaseModel, Field


class AppCreateResponse(BaseModel):
    """Acknowledgement returned when an app creation request is accepted."""

    message: str = Field(
        ...,
        description="Human-readable status message.",
        examples=["App creation requested"],
    )
    request_id: int = Field(
        ...,
        examples=[101],
    )

    job_id: int = Field(
        ...,
        examples=[501],
    )

    status: str = Field(
        ...,
        examples=["pending"],
    )