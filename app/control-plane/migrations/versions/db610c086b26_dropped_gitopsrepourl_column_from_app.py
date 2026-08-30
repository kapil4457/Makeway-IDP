"""dropped gitOpsRepoUrl column from app

gitOpsRepoUrl was a platform constant (the Makeway platform repo URL) — the
same value in every row — so it no longer belongs in the per-app schema.
The per-app handle ``gitOpsPath`` (argocd/apps/<appName>/) remains; the repo
URL is exposed as constant config (core.config.GITOPS_REPO_URL) for deep links.

Revision ID: db610c086b26
Revises: 96cf4f390121
Create Date: 2026-08-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'db610c086b26'
down_revision: Union[str, Sequence[str], None] = '96cf4f390121'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column('app', 'gitOpsRepoUrl')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        'app',
        sa.Column('gitOpsRepoUrl', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )