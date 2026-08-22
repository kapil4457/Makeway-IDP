import pydantic
from pydantic import Field

from ..enums.environment import Environment
from .capability import Capability
from .service_config import ServiceConfig


class EnvConfig(pydantic.BaseModel):
    """The services an application runs in a single environment."""

    env: Environment = Field(
        default=Environment.DEV,
        description="Environment the application is provisioned into.",
        examples=["dev"],
    )
    services: list[ServiceConfig] = Field(
        default_factory=list,
        description="Services deployed in this environment.",
    )
    capabilities: list[Capability] = Field(
        default_factory=list,
        description="Capabilities the application may use in this environment.",
    )