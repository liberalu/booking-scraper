"""add lifecycle_state to validation_issues

Revision ID: d1f2e5b8a9c4
Revises: c8e9f4a1b3d2
Create Date: 2026-04-17 11:00:00.000000

Adds lifecycle_state enum (new/recurring/already_seen) and
acknowledged_at timestamp. Every existing row gets lifecycle_state =
'recurring' — they've already been observed, and treating them as
'new' would defeat the whole point of the triage bucket.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1f2e5b8a9c4"
down_revision: Union[str, Sequence[str], None] = "c8e9f4a1b3d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE validation_lifecycle AS ENUM ('new', 'recurring', 'already_seen')")
    op.add_column(
        "validation_issues",
        sa.Column(
            "lifecycle_state",
            sa.Enum(
                "new",
                "recurring",
                "already_seen",
                name="validation_lifecycle",
                create_type=False,
            ),
            nullable=False,
            server_default="new",
        ),
    )
    op.add_column(
        "validation_issues",
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_validation_issues_lifecycle_state",
        "validation_issues",
        ["lifecycle_state"],
    )
    op.execute("UPDATE validation_issues SET lifecycle_state = 'recurring'")


def downgrade() -> None:
    op.drop_index(
        "ix_validation_issues_lifecycle_state",
        table_name="validation_issues",
    )
    op.drop_column("validation_issues", "acknowledged_at")
    op.drop_column("validation_issues", "lifecycle_state")
    op.execute("DROP TYPE validation_lifecycle")
