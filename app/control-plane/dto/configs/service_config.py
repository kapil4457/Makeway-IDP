from typing import Optional

import pydantic
from pydantic import Field

from dto.enums.service_type import ServiceType


class ServiceConfig(pydantic.BaseModel):
    """A single deployable service within an environment."""

    service_type: ServiceType = Field(
        ...,
        description="Golden-path stack used to scaffold the service.",
        examples=["fast-api"],
    )
    service_name: Optional[str] = Field(
        default=None,
        description=(
            "Optional name for the service. If omitted, defaults to the service "
            "type. Must be a DNS-1035 label: lowercase letters/digits/hyphens, "
            "starting with a letter and ending with a letter or digit — the name "
            "becomes the k8s Service/Deployment/container name (Service rejects "
            "DNS-1035 violations, e.g. 'node_service' with an underscore)."
        ),
        examples=["orders-api"],
        min_length=1,
        max_length=63,
        pattern=r"^[a-z]([-a-z0-9]*[a-z0-9])?$",
    )