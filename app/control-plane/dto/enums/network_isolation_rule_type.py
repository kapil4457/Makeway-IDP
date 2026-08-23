from enum import Enum

class NetworkIsolationRuleType(str, Enum):
    """Type of a network isolation rule in the Makeway platform."""

    K8S_NETWORK_POLICY = "k8s_network_policy"
    SECURITY_GROUP = "security_group"