from enum import Enum


class ServiceHealth(str, Enum):
    """Runtime health of a deployed service.

    ``UNKNOWN`` is the honest default until a reporter (e.g. ArgoCD health,
    live readiness probe) fills a value in — the status endpoint marks
    ``dataSource="persisted"`` on unknown rows instead of inventing health.
    """

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"