"""cascade url_classifications.discovered_url_id fk

Production carries `ON DELETE CASCADE` on this foreign key. No migration and
no model ever declared it — someone ALTERed the catalogue by hand, and the
schema comparison built for the PHP port is what surfaced it: a database
migrated to head differed from production by this one line and nothing else.

This revision makes the declared schema match the running one. It asserts the
cascade was intended, which is the reading the data supports: a
`url_classifications` row describes one `discovered_urls` row, so it has no
meaning once that row is gone, and without the cascade deleting a discovered
URL fails on the foreign key instead.

Idempotent by construction: dropping and re-adding the constraint reaches the
same end state whether or not the cascade was already there, so this applies
cleanly to production (already cascading) and to any database built from
migrations (not cascading).

Revision ID: b7f4c2a91e05
Revises: a3c8e1f92d74
Create Date: 2026-08-25 12:10:00.000000

"""

from alembic import op

revision = "b7f4c2a91e05"
down_revision = "a3c8e1f92d74"
branch_labels = None
depends_on = None

_TABLE = "url_classifications"
_FK = "url_classifications_discovered_url_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.create_foreign_key(
        _FK,
        _TABLE,
        "discovered_urls",
        ["discovered_url_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.create_foreign_key(
        _FK,
        _TABLE,
        "discovered_urls",
        ["discovered_url_id"],
        ["id"],
    )
