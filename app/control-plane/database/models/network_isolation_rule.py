from sqlmodel import Field, UniqueConstraint
from .shared_audit import SharedAudit
from dto.enums.network_isolation_rule_type import NetworkIsolationRuleType

class NetworkIsolationRule(SharedAudit, table=True):
    ruleId: int = Field(primary_key=True)
    ruleType: NetworkIsolationRuleType = Field(nullable=False)
    targetRef: str = Field(nullable=False)
    status: str = Field(nullable=False)

    namespaceId: int = Field(nullable=False, foreign_key="namespace.namespaceId", index=True)
