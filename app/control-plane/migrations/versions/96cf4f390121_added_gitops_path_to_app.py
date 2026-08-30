"""added gitOpsPath to app

The gitops config lives inside the Makeway platform repo (no per-app gitops
repo), so the per-app handle is the folder path under argocd/apps/. This
revision supplements gitOpsRepoUrl (repo root, same for every app) with the
app's exact folder, e.g. ``argocd/apps/order-service/``.

Revision ID: 96cf4f390121
Revises: f987a0ced74d
Create Date: 2026-08-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '96cf4f390121'
down_revision: Union[str, Sequence[str], None] = 'f987a0ced74d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('app', sa.Column('gitOpsPath', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('app', 'gitOpsPath')