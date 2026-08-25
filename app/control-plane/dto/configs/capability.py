from typing import Annotated

import pydantic
from pydantic import Field, Tag

from .database_config import DatabaseConfig
from .messaging_config import MessagingConfig
from .observability_config import ObservabilityConfig
from .storage_config import StorageConfig
from dto.enums.capability_types import CapabilityType

# A config's `type` field (e.g. "storage") selects which capability schema the
# `config` object is validated against. The union below is keyed on that field.
CapabilityConfig = Annotated[
    Annotated[StorageConfig, Tag(CapabilityType.STORAGE)]
    | Annotated[ObservabilityConfig, Tag(CapabilityType.OBSERVABILITY)]
    | Annotated[MessagingConfig, Tag(CapabilityType.MESSAGING)]
    | Annotated[DatabaseConfig, Tag(CapabilityType.REL_DATABASE)],
    pydantic.Field(discriminator="type"),
]


class Capability(pydantic.BaseModel):
    """A capability bound to one or more services in an environment.

    The `type` discriminator lives on the `config` object itself: it selects
    which of the platform capability schemas the config validates against and
    is the single source of truth for routing.
    """

    config: CapabilityConfig = Field(
        ...,
        description="Configuration for this capability. Its `type` discriminator "
        "selects which platform capability schema it validates against.",
    )
    access_to: list[str] = Field(
        default_factory=list,
        description="Service names that may use this capability. Empty means all services in the environment.",
        examples=[["orders-api"]],
    )