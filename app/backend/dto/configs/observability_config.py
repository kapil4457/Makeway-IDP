from typing import Literal

import pydantic
from pydantic import Field


class ObservabilityConfig(pydantic.BaseModel):
    """Observability signals wired into the application's environments."""

    type: Literal["observability"] = Field(
        default="observability",
        description="Discriminator identifying this as an observability capability.",
        examples=["observability"],
    )
    logs: bool = Field(
        default=False,
        description="Ship application logs to the central log store.",
        examples=[True],
    )
    metrics: bool = Field(
        default=False,
        description="Emit application metrics to the platform monitoring stack.",
        examples=[True],
    )
    traces: bool = Field(
        default=False,
        description="Enable distributed tracing via OpenTelemetry.",
        examples=[False],
    )
