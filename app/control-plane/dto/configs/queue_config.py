import pydantic
from pydantic import Field


class QueueConfig(pydantic.BaseModel):
    """Queue capabilities available to the application."""

    name: str = Field(
        default="default",
        description="Name of the message queue.",
        examples=["orders-queue"],
    )
