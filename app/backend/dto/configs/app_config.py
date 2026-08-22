import pydantic
from pydantic import ConfigDict, Field

from .env_config import EnvConfig


class AppConfig(pydantic.BaseModel):
    """Desired state for a new application onboarded onto the Forge platform."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "app_name": "order-service",
                    "env_config": [
                        {
                            "env": "dev",
                            "services": [
                                {
                                    "service_type": "fast-api",
                                    "service_name": "orders-api",
                                },
                                {
                                    "service_type": "node-js",
                                    "service_name": "web",
                                },
                            ],
                            "capabilities": [
                                {
                                    "config": {
                                        "type": "rel_database",
                                        "name": "orders",
                                        "username": "orders_admin",
                                        "capacity": 5,
                                    },
                                    "access_to": ["orders-api"],
                                },
                                {
                                    "config": {
                                        "type": "cache",
                                        "capacity": 10,
                                        "ttl": 300,
                                    },
                                    "access_to": ["orders-api"],
                                },
                                {
                                    "config": {
                                        "type": "storage",
                                        "s3": {
                                            "region": "us-east-1",
                                            "cloudfront": True,
                                        },
                                    },
                                    "access_to": ["orders-api"],
                                },
                                {
                                    "config": {
                                        "type": "messaging",
                                        "notification": True,
                                        "queue": [{"name": "orders-queue"}],
                                    },
                                    "access_to": ["orders-api", "web"],
                                },
                                {
                                    "config": {
                                        "type": "observability",
                                        "logs": True,
                                        "metrics": True,
                                        "traces": False,
                                    },
                                    "access_to": ["orders-api", "web"],
                                },
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
    env_config: list[EnvConfig] = Field(
        default_factory=list,
        description="Per-environment configuration of the application's services.",
    )