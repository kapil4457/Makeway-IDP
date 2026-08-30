import pydantic
from pydantic import ConfigDict, Field

from .env_config import EnvConfig

class AppConfig(pydantic.BaseModel):
    """Desired state for a new application onboarded onto the Makeway platform."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "app_name": "zomato",
                    "team_name": "platform",
                    "env_config": [
                        {
                            "env": "qa",
                            "services": [
                                {
                                    "service_type": "fast-api",
                                    "service_name": "order-service",
                                },
                                {
                                    "service_type": "node-js",
                                    "service_name": "media-service",
                                },
                            ],
                            "capabilities": [
                                {
                                    "config": {
                                        "type": "rel_database",
                                        "name": "order",
                                        "username": "orders_admin",
                                        "capacity": 5,
                                    },
                                    "access_to": ["order-service"],
                                },
                                {
                                    "config": {
                                        "type": "storage",
                                        "s3": {
                                            "region": "ap-south-1",
                                            "cloudfront": True,
                                        },
                                    },
                                    "access_to": ["order-service","media-service"],
                                },
                                {
                                    "config": {
                                        "type": "messaging",
                                        "notification": True,
                                        "queue": [{"name": "order-queue"}],
                                    },
                                    "access_to": ["order-service"],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )

    app_name: str = Field(
        ...,
        description="Unique application name (lowercase kebab-case). Used to name the "
        "repository, Kubernetes namespace, and cloud resources.",
        examples=["order-service"],
        min_length=3,
        max_length=50,
        pattern=r"^[a-z0-9]([a-z0-9 -]*[a-z0-9])?$",
    )
    team_name: str =  Field(
        ...,
        description="Team for which this application is being created for",
        examples=["orders"]
    )
    env_config: list[EnvConfig] = Field(
        default_factory=list,
        description="Per-environment configuration of the application's services.",
    )