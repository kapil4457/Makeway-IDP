from typing import Literal

import pydantic
from pydantic import Field

from .queue_config import QueueConfig


class MessagingConfig(pydantic.BaseModel):
    """Messaging capabilities available to the application."""

    type: Literal["messaging"] = Field(
        default="messaging",
        description="Discriminator identifying this as a messaging capability.",
        examples=["messaging"],
    )
    notification: bool = Field(
        default=False,
        description="Enable outbound notifications (e-mail, SMS, push) via the platform notification service.",
        examples=[True],
    )
    
    queue: list[QueueConfig] = Field(
        default_factory=list,
        description="Provision a message queue for asynchronous, decoupled workloads.",
        examples=[],
    )
