from typing import Literal, Optional

import pydantic
from pydantic import Field


class DatabaseConfig(pydantic.BaseModel):
    """Relational database provisioning settings."""

    type: Literal["rel_database"] = Field(
        default="rel_database",
        description="Discriminator identifying this as a relational-database capability.",
        examples=["rel_database"],
    )
    name: str = Field(
        ...,
        description=(
            "Name of the database to provision. SQL-safe identifier: lowercase "
            "letters, digits, underscores — hyphens are invalid unquoted "
            "database identifiers and AWS RDS rejects them. Mirrors the "
            "RelationalDatabase XRD's databaseName pattern."
        ),
        examples=["orders"],
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9_]+$",
    )
    username: Optional[str] = Field(
        default=None,
        description="Master username for the database. Stored in Vault once provisioned.",
        examples=["orders_admin"],
    )
    capacity: Optional[int] = Field(
        default=None,
        description="Capacity tier of the database instance (1 = smallest, 10 = largest).",
        examples=[5],
        ge=1,
        le=10,
    )
