from enum import Enum


class ServiceType(str, Enum):
    """Golden-path application stacks supported by Makeway."""

    SPRING_BOOT = "spring-boot"
    FAST_API = "fast-api"
    NODE_JS = "node-js"