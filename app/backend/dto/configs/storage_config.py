from typing import Literal, Optional

import pydantic
from pydantic import Field

from .s3_config import S3Config


class StorageConfig(pydantic.BaseModel):
    """Storage capabilities attached to the application."""
    type: Literal["storage"] = Field(
        default="storage",
        description="Discriminator identifying this as an object-storage capability.",
        examples=["storage"],
    )
    s3: Optional[S3Config] = Field(
        default=None,
        description="S3 object storage. Omit when the app does not need object storage.",
    )
