import pydantic
from pydantic import Field

from ..enums.environment import Environment
from .capability import Capability
from .service_config import ServiceConfig


class CapabilityAccessPatch(pydantic.BaseModel):
    """Replaces one capability's access bindings for one environment.

    Sent in the update flow when a capability keeps its config but the set of
    services that may use it changes. ``access_to`` is the FULL desired list —
    bindings missing from it are torn down, the rest are kept/created.
    """

    capability_id: int = Field(
        ...,
        description="Capability whose access bindings are replaced. The id is "
                    "what the status read exposes per environment.",
        examples=[23],
    )
    access_to: list[str] = Field(
        ...,
        description="Full desired list of base service names allowed to use "
                    "this capability in this environment. Must not be empty — "
                    "an unbound capability is invisible to the status read "
                    "and the workers.",
        examples=[["orders-api", "payment"]],
    )


class EnvConfig(pydantic.BaseModel):
    """The services an application runs in a single environment."""

    env: Environment = Field(
        default=Environment.QA,
        description="Environment the application is provisioned into.",
        examples=["qa"],
    )
    services: list[ServiceConfig] = Field(
        default_factory=list,
        description="Services deployed in this environment.",
    )
    capabilities: list[Capability] = Field(
        default_factory=list,
        description="Capabilities the application may use in this environment.",
    )
    remove_services: list[str] = Field(
        default_factory=list,
        description="Base service names to remove from this environment "
                    "(update flow only — creation rejects removals). Removing a "
                    "service takes its access bindings with it.",
        examples=[["payment"]],
    )
    remove_capabilities: list[str] = Field(
        default_factory=list,
        description="Capability types to remove for this environment (update "
                    "flow only — creation rejects removals). The capability's "
                    "provisioned infrastructure is torn down.",
        examples=[["messaging"]],
    )
    update_access: list[CapabilityAccessPatch] = Field(
        default_factory=list,
        description="Access-binding replacements for existing capabilities "
                    "(update flow only — creation rejects them). Each patch "
                    "replaces the capability's bindings in this environment; "
                    "bindings in other environments are untouched.",
    )