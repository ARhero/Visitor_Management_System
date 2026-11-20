"""gate names unique per site

Revision ID: 3bc197ecf9d7
Revises: 0e284c6b603d
Create Date: 2026-11-19 16:28:25.956506
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3bc197ecf9d7"
down_revision: str | None = "0e284c6b603d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rename any existing duplicates ("Side Gate", "side gate" -> "side gate (2)") first.
    op.execute(
        """
        UPDATE gates g SET name = left(g.name, 94) || ' (' || d.n || ')'
        FROM (
            SELECT id, row_number() OVER (
                PARTITION BY org_id, site_id, lower(name) ORDER BY created_at, id
            ) AS n
            FROM gates
        ) d
        WHERE g.id = d.id AND d.n > 1
        """
    )
    op.create_index(
        "uq_gates_site_name",
        "gates",
        ["org_id", "site_id", sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_gates_site_name", table_name="gates")
