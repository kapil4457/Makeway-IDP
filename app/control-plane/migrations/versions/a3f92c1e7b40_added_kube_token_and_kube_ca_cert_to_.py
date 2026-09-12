"""added kubeToken and kubeCaCert columns to cluster

The Cluster registry is becoming the runtime source of truth for per-environment
cluster access: each registered cluster now optionally carries the makeway-worker
ServiceAccount bearer token and the base64 apiserver CA bundle. Rows (and test
seeds) may omit both — the Step-2 worker falls back to its Lambda env
KUBE_TOKEN / KUBE_CA_CERT for clusters without them.

Revision ID: a3f92c1e7b40
Revises: db610c086b26
Create Date: 2026-08-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a3f92c1e7b40'
down_revision: Union[str, Sequence[str], None] = 'db610c086b26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('cluster', sa.Column('kubeToken', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('cluster', sa.Column('kubeCaCert', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('cluster', 'kubeCaCert')
    op.drop_column('cluster', 'kubeToken')