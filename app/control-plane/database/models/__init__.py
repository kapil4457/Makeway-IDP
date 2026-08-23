"""
database/models/__init__.py

Central model registry. Every SQLModel table class must be imported here
so SQLModel.metadata knows about it before create_all() (or Alembic
autogenerate) runs.

shared_audit.py is not imported here - it's a mixin, not a
table itself. It gets pulled in automatically when the models below
import it.

When adding a new table:
  1. Create the model in its own file under database/models/.
  2. Import it here.
That's the only registration step required.
"""

from database.models.team import Team
from database.models.user import User
from database.models.team_member import TeamMember
from database.models.app import App
from database.models.cluster import Cluster
from database.models.environment import Environment
from database.models.service import Service
from database.models.namespace import Namespace
from database.models.capability import Capability
from database.models.infra_requirement import InfraRequirement
from database.models.access_binding import AccessBinding
from database.models.network_isolation_rule import NetworkIsolationRule
from database.models.deployment_setup import DeploymentSetup
from database.models.request import Request
from database.models.job import Job

__all__ = [
    "Team",
    "User",
    "TeamMember",
    "App",
    "Cluster",
    "Environment",
    "Service",
    "Namespace",
    "Capability",
    "InfraRequirement",
    "AccessBinding",
    "NetworkIsolationRule",
    "DeploymentSetup",
    "Request",
    "Job",
]