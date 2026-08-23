from typing import Literal

import pydantic
from pydantic import Field


class CacheConfig(pydantic.BaseModel):
    """In-memory cache settings."""

    type: Literal["cache"] = Field(
        default="cache",
        description="Discriminator identifying this as an in-memory cache capability.",
        examples=["cache"],
    )
    capacity: int = Field(
        default=0,
        description="Capacity tier of the cache cluster (0 = platform default).",
        examples=[10],
        ge=0,
    )
    ttl: int = Field(
        default=0,
        description="Default time-to-live for cached entries, in seconds (0 = no expiry).",
        examples=[300],
        ge=0,
    )
