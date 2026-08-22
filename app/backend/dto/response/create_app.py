from pydantic import BaseModel, Field


class AppCreateResponse(BaseModel):
    """Acknowledgement returned when an app creation request is accepted."""

    message: str = Field(
        ...,
        description="Human-readable status message.",
        examples=["App creation requested"],
    )
    app_name: str = Field(
        ...,
        description="Name of the application that was requested.",
        examples=["order-service"],
    )
