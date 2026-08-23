from enum import Enum
from typing import Optional

import pydantic
from pydantic import Field


class ServiceType(str, Enum):
    """Golden-path application stacks supported by Makeway."""

    SPRING_BOOT = "spring-boot"
    FAST_API = "fast-api"
    NODE_JS = "node-js"


class ServiceConfig(pydantic.BaseModel):
    """A single deployable service within an environment."""

    service_type: ServiceType = Field(
        ...,
        description="Golden-path stack used to scaffold the service.",
        examples=["fast-api"],
    )
    service_name: Optional[str] = Field(
        default=None,
        description="Optional name for the service. If omitted, defaults to the service type.",
        examples=["orders-api"],
    )