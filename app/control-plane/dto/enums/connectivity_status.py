from enum import Enum


class ConnectivityStatus(str, Enum):
    """State of a service-to-capability binding.

    ``CONFIGURED`` means the access intent exists (a CapabilityAccess row
    grants the service the capability) but live reachability has not been
    verified — a probe/NetworkPolicy check would move it to HEALTHY or FAILED.
    """

    UNKNOWN = "unknown"
    CONFIGURED = "configured"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"