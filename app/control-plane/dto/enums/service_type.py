from enum import Enum

class ServiceType(str,Enum):
    """Type of a service in the Makeway platform."""

    SPRING_BOOT = "spring-boot"
    FASTAPI = "fastapi"
    NODEJS = "nodejs"