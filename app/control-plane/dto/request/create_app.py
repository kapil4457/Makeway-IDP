from typing import Optional

import pydantic
from pydantic import Field

from ..configs.app_config import AppConfig


class CreateApp(pydantic.BaseModel):
    """Request envelope for app creation, carrying the caller's identity."""

    app_config: AppConfig = Field(
        ...,
        description="Desired application configuration.",
    )
    requester_id: Optional[str] = Field(
        default=None,
        description="Identifier of the user or automation requesting the app.",
        examples=["kapil@example.com"],
    )
