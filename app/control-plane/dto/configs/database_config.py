from typing import Literal, Optional

import pydantic
from pydantic import Field

# RDS refuses these as master usernames at CreateDBInstance ("reserved word
# used by the engine") — reject at the request boundary instead of letting the
# Crossplane provision fail mid-workflow.
RESERVED_MASTER_USERNAMES = frozenset({"admin", "administrator", "root", "rdsadmin"})


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
        description=(
            "Master username for the database. Must not be an RDS-reserved "
            "name (admin, administrator, root, rdsadmin). Stored in Vault "
            "once provisioned; omit to use the platform default."
        ),
        examples=["orders_admin"],
    )

    @pydantic.field_validator("username")
    @classmethod
    def _reject_reserved_master_usernames(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip().lower() in RESERVED_MASTER_USERNAMES:
            raise ValueError(
                f"'{v.strip()}' is reserved by RDS and cannot be used as a master "
                "username (reserved: admin, administrator, root, rdsadmin) — "
                "pick another name or omit username for the platform default."
            )
        return v
    capacity: Optional[int] = Field(
        default=None,
        description="Capacity tier of the database instance (1 = smallest, 10 = largest).",
        examples=[5],
        ge=1,
        le=10,
    )
