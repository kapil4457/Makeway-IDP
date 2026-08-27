"""fix servicetype enum labels to match python enum names

Revision ID: 4a3679022ce2
Revises: 9dc305737214
Create Date: 2026-08-27 14:44:43.706942

The initial schema created the ``servicetype`` Postgres enum with labels
``SPRING_BOOT``, ``FASTAPI`` and ``NODEJS``, but SQLAlchemy persists the
Python enum *member names* — ``SPRING_BOOT``, ``FAST_API``, ``NODE_JS``
(see ``dto/enums/service_type.py``). Every insert of a FAST_API or NODE_JS
service therefore failed with ``invalid input value for enum servicetype``.

Postgres cannot rename or remove enum labels, so the type is swapped out
from under the column: rename the old type, create the corrected one, cast
the column across (mapping any pre-existing rows), then drop the old type.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '4a3679022ce2'
down_revision: Union[str, Sequence[str], None] = '9dc305737214'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (old label, new label) pairs for rows that may already exist.
_LABEL_RENAMES = (("FASTAPI", "FAST_API"), ("NODEJS", "NODE_JS"))


def _swap_servicetype_labels(new_labels: tuple[str, ...], renames: tuple[tuple[str, str], ...]) -> None:
    labels = ", ".join(f"'{label}'" for label in new_labels)
    when_clauses = " ".join(
        f"WHEN '{old}' THEN '{new}'" for old, new in renames
    )
    op.execute("ALTER TYPE servicetype RENAME TO servicetype_old")
    op.execute(f"CREATE TYPE servicetype AS ENUM ({labels})")
    op.execute(
        'ALTER TABLE service ALTER COLUMN "serviceType" TYPE servicetype USING '
        f'(CASE "serviceType"::text {when_clauses} ELSE "serviceType"::text END)::servicetype'
    )
    op.execute("DROP TYPE servicetype_old")


def upgrade() -> None:
    """Upgrade schema."""
    _swap_servicetype_labels(
        new_labels=("SPRING_BOOT", "FAST_API", "NODE_JS"),
        renames=_LABEL_RENAMES,
    )


def downgrade() -> None:
    """Downgrade schema."""
    _swap_servicetype_labels(
        new_labels=("SPRING_BOOT", "FASTAPI", "NODEJS"),
        renames=tuple((new, old) for old, new in _LABEL_RENAMES),
    )
