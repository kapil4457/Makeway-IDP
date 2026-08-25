import pydantic
from pydantic import Field


class S3Config(pydantic.BaseModel):
    """Amazon S3 object-storage settings."""

    region: str = Field(
        ...,
        description="AWS region where the bucket is provisioned.",
        examples=["ap-south-1"],
    )
    cloudfront: bool = Field(
        default=False,
        description="Front the bucket with a CloudFront CDN distribution.",
        examples=[True],
    )
