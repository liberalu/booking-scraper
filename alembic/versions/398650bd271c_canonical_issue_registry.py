"""canonical issue registry

Revision ID: 398650bd271c
Revises: f1a2b3c4d5e6
Create Date: 2026-05-12

Transforms validation_issues from append-only log to canonical registry:
one row per (entity, field, issue_type). Adds shop_id, first/last_seen_run_id,
run_count, resolved_at, snoozed_until. Alters enum: drops recurring/already_seen,
adds acknowledged/snoozed/resolved. Deduplicates existing rows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "398650bd271c"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add new columns (all nullable initially for safe backfill)
    op.add_column("validation_issues", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.add_column("validation_issues", sa.Column("first_seen_run_id", sa.Integer(), nullable=True))
    op.add_column("validation_issues", sa.Column("run_count", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("validation_issues", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("validation_issues", sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True))

    # 2. Rename scrape_run_id -> last_seen_run_id
    op.alter_column("validation_issues", "scrape_run_id", new_column_name="last_seen_run_id")

    conn = op.get_bind()

    # 3. Backfill shop_id (shop_book → discovered_url → scrape_run fallback)
    conn.execute(text("""
        UPDATE validation_issues vi
        SET shop_id = sb.shop_id
        FROM shop_books sb
        WHERE vi.shop_book_id = sb.id AND vi.shop_id IS NULL
    """))
    conn.execute(text("""
        UPDATE validation_issues vi
        SET shop_id = du.shop_id
        FROM discovered_urls du
        WHERE vi.discovered_url_id = du.id AND vi.shop_id IS NULL
    """))
    conn.execute(text("""
        UPDATE validation_issues vi
        SET shop_id = sr.shop_id
        FROM scrape_runs sr
        WHERE vi.last_seen_run_id = sr.id AND vi.shop_id IS NULL
    """))

    # 4. Backfill first_seen_run_id = last_seen_run_id
    conn.execute(text("UPDATE validation_issues SET first_seen_run_id = last_seen_run_id"))

    # 5. Migrate enum: TEXT intermediate → new type
    #    PostgreSQL does not support DROP VALUE or RENAME VALUE on enums, so we recreate.
    #    scrape_failures also uses validation_lifecycle — must migrate it alongside.
    #    Must drop DEFAULTs first (they reference the old enum type) before type changes.
    conn.execute(text("ALTER TABLE validation_issues ALTER COLUMN lifecycle_state DROP DEFAULT"))
    conn.execute(text("ALTER TABLE validation_issues ALTER COLUMN lifecycle_state TYPE TEXT"))
    conn.execute(text("UPDATE validation_issues SET lifecycle_state = 'acknowledged' WHERE lifecycle_state = 'already_seen'"))
    conn.execute(text("UPDATE validation_issues SET lifecycle_state = 'new' WHERE lifecycle_state = 'recurring'"))
    # Drop partial index on scrape_failures that references old enum literal before type change
    conn.execute(text("DROP INDEX IF EXISTS ix_scrape_failures_lifecycle_open"))
    conn.execute(text("ALTER TABLE scrape_failures ALTER COLUMN lifecycle_state DROP DEFAULT"))
    conn.execute(text("ALTER TABLE scrape_failures ALTER COLUMN lifecycle_state TYPE TEXT"))
    conn.execute(text("UPDATE scrape_failures SET lifecycle_state = 'acknowledged' WHERE lifecycle_state = 'already_seen'"))
    conn.execute(text("UPDATE scrape_failures SET lifecycle_state = 'new' WHERE lifecycle_state = 'recurring'"))
    conn.execute(text("ALTER TYPE validation_lifecycle RENAME TO validation_lifecycle_old"))
    conn.execute(text("CREATE TYPE validation_lifecycle AS ENUM ('new', 'acknowledged', 'snoozed', 'resolved')"))
    conn.execute(text("""
        ALTER TABLE validation_issues
        ALTER COLUMN lifecycle_state TYPE validation_lifecycle
        USING lifecycle_state::validation_lifecycle
    """))
    conn.execute(text("ALTER TABLE validation_issues ALTER COLUMN lifecycle_state SET DEFAULT 'new'::validation_lifecycle"))
    conn.execute(text("""
        ALTER TABLE scrape_failures
        ALTER COLUMN lifecycle_state TYPE validation_lifecycle
        USING lifecycle_state::validation_lifecycle
    """))
    conn.execute(text("ALTER TABLE scrape_failures ALTER COLUMN lifecycle_state SET DEFAULT 'new'::validation_lifecycle"))
    conn.execute(text("DROP TYPE validation_lifecycle_old"))
    # Recreate the partial index with new enum value (acknowledged replaces already_seen)
    conn.execute(text("""
        CREATE INDEX ix_scrape_failures_lifecycle_open
        ON scrape_failures (lifecycle_state)
        WHERE lifecycle_state <> 'acknowledged'::validation_lifecycle
    """))

    # 6. Data deduplication: collapse groups using the same granularity as the target indexes.
    #    Three separate passes matching each index's grouping key.
    #    was_acked: check both acknowledged_at IS NOT NULL AND lifecycle_state = 'acknowledged'
    #    (enum conversion step 5 sets lifecycle_state = 'acknowledged' but leaves acknowledged_at NULL)
    def _dedup(conn, query: str) -> None:
        result = conn.execute(text(query))
        for row in result:
            keep_id = row.ids[0]
            delete_ids = list(row.ids[1:])
            conn.execute(text("""
                UPDATE validation_issues
                SET first_seen_run_id = :min_run_id,
                    run_count         = :cnt,
                    lifecycle_state   = CASE
                        WHEN :was_acked THEN 'acknowledged'::validation_lifecycle
                        ELSE lifecycle_state
                    END
                WHERE id = :keep_id
            """), {"min_run_id": row.min_run_id, "cnt": int(row.cnt),
                   "was_acked": bool(row.was_acked), "keep_id": keep_id})
            if delete_ids:
                conn.execute(
                    text("DELETE FROM validation_issues WHERE id = ANY(:ids)"),
                    {"ids": delete_ids},
                )

    # Pass A: shop_book_id-keyed dupes (matches uix_vi_shop_book_field_issue)
    _dedup(conn, """
        SELECT shop_book_id, field, issue,
               array_agg(id ORDER BY id DESC)                                          AS ids,
               MIN(first_seen_run_id)                                                  AS min_run_id,
               COUNT(*)                                                                AS cnt,
               BOOL_OR(acknowledged_at IS NOT NULL OR lifecycle_state = 'acknowledged') AS was_acked
        FROM validation_issues
        WHERE shop_book_id IS NOT NULL
        GROUP BY shop_book_id, field, issue
        HAVING COUNT(*) > 1
    """)
    # Pass B: discovered_url_id-keyed dupes (matches uix_vi_discovered_url_field_issue)
    _dedup(conn, """
        SELECT discovered_url_id, field, issue,
               array_agg(id ORDER BY id DESC)                                          AS ids,
               MIN(first_seen_run_id)                                                  AS min_run_id,
               COUNT(*)                                                                AS cnt,
               BOOL_OR(acknowledged_at IS NOT NULL OR lifecycle_state = 'acknowledged') AS was_acked
        FROM validation_issues
        WHERE discovered_url_id IS NOT NULL
        GROUP BY discovered_url_id, field, issue
        HAVING COUNT(*) > 1
    """)
    # Pass C: url-only keyed dupes (matches uix_vi_url_field_issue)
    _dedup(conn, """
        SELECT url, field, issue,
               array_agg(id ORDER BY id DESC)                                          AS ids,
               MIN(first_seen_run_id)                                                  AS min_run_id,
               COUNT(*)                                                                AS cnt,
               BOOL_OR(acknowledged_at IS NOT NULL OR lifecycle_state = 'acknowledged') AS was_acked
        FROM validation_issues
        WHERE shop_book_id IS NULL AND discovered_url_id IS NULL
        GROUP BY url, field, issue
        HAVING COUNT(*) > 1
    """)

    # Delete any rows we couldn't backfill (should be zero on a clean DB)
    conn.execute(text("DELETE FROM validation_issues WHERE shop_id IS NULL"))

    # 7. Add FK constraints and NOT NULL on shop_id
    op.create_foreign_key("fk_vi_shop_id", "validation_issues", "shops", ["shop_id"], ["id"])
    op.create_foreign_key("fk_vi_first_seen_run_id", "validation_issues", "scrape_runs",
                          ["first_seen_run_id"], ["id"])
    op.alter_column("validation_issues", "shop_id", nullable=False)

    # 8. Partial unique indexes
    op.create_index(
        "uix_vi_shop_book_field_issue",
        "validation_issues",
        ["shop_book_id", "field", "issue"],
        unique=True,
        postgresql_where=sa.text("shop_book_id IS NOT NULL"),
    )
    op.create_index(
        "uix_vi_discovered_url_field_issue",
        "validation_issues",
        ["discovered_url_id", "field", "issue"],
        unique=True,
        postgresql_where=sa.text("discovered_url_id IS NOT NULL"),
    )
    op.create_index(
        "uix_vi_url_field_issue",
        "validation_issues",
        ["url", "field", "issue"],
        unique=True,
        postgresql_where=sa.text("shop_book_id IS NULL AND discovered_url_id IS NULL"),
    )
    op.create_index("ix_vi_shop_id_lifecycle", "validation_issues",
                    ["shop_id", "lifecycle_state"])


def downgrade() -> None:
    op.drop_index("ix_vi_shop_id_lifecycle", "validation_issues")
    op.drop_index("uix_vi_url_field_issue", "validation_issues")
    op.drop_index("uix_vi_discovered_url_field_issue", "validation_issues")
    op.drop_index("uix_vi_shop_book_field_issue", "validation_issues")
    op.drop_constraint("fk_vi_first_seen_run_id", "validation_issues", type_="foreignkey")
    op.drop_constraint("fk_vi_shop_id", "validation_issues", type_="foreignkey")

    conn = op.get_bind()
    # Drop partial index on scrape_failures that references new enum literal before downgrade
    conn.execute(text("DROP INDEX IF EXISTS ix_scrape_failures_lifecycle_open"))
    conn.execute(text("ALTER TABLE validation_issues ALTER COLUMN lifecycle_state DROP DEFAULT"))
    conn.execute(text("ALTER TABLE validation_issues ALTER COLUMN lifecycle_state TYPE TEXT"))
    conn.execute(text("ALTER TABLE scrape_failures ALTER COLUMN lifecycle_state DROP DEFAULT"))
    conn.execute(text("ALTER TABLE scrape_failures ALTER COLUMN lifecycle_state TYPE TEXT"))
    conn.execute(text("ALTER TYPE validation_lifecycle RENAME TO validation_lifecycle_old"))
    conn.execute(text("CREATE TYPE validation_lifecycle AS ENUM ('new', 'recurring', 'already_seen')"))
    conn.execute(text("""
        ALTER TABLE validation_issues
        ALTER COLUMN lifecycle_state TYPE validation_lifecycle
        USING (CASE lifecycle_state
            WHEN 'acknowledged' THEN 'already_seen'
            WHEN 'snoozed'      THEN 'new'
            WHEN 'resolved'     THEN 'new'
            ELSE lifecycle_state
        END)::validation_lifecycle
    """))
    conn.execute(text("ALTER TABLE validation_issues ALTER COLUMN lifecycle_state SET DEFAULT 'new'::validation_lifecycle"))
    conn.execute(text("""
        ALTER TABLE scrape_failures
        ALTER COLUMN lifecycle_state TYPE validation_lifecycle
        USING (CASE lifecycle_state
            WHEN 'acknowledged' THEN 'already_seen'
            WHEN 'snoozed'      THEN 'new'
            WHEN 'resolved'     THEN 'new'
            ELSE lifecycle_state
        END)::validation_lifecycle
    """))
    conn.execute(text("ALTER TABLE scrape_failures ALTER COLUMN lifecycle_state SET DEFAULT 'new'::validation_lifecycle"))
    conn.execute(text("DROP TYPE validation_lifecycle_old"))

    # Restore old partial index using old enum value
    conn.execute(text("""
        CREATE INDEX ix_scrape_failures_lifecycle_open
        ON scrape_failures (lifecycle_state)
        WHERE lifecycle_state <> 'already_seen'::validation_lifecycle
    """))

    op.alter_column("validation_issues", "last_seen_run_id", new_column_name="scrape_run_id")
    op.drop_column("validation_issues", "snoozed_until")
    op.drop_column("validation_issues", "resolved_at")
    op.drop_column("validation_issues", "run_count")
    op.drop_column("validation_issues", "first_seen_run_id")
    op.drop_column("validation_issues", "shop_id")
