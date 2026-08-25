#!/usr/bin/env bash
#
# Regenerate `php/schema/0001_baseline.sql` from a reference database.
#
# The baseline is not hand-written and must never be hand-edited: it is
# `pg_dump --schema-only` of the schema Alembic built, kept verbatim so it
# cannot drift from it. Re-run this if Alembic gains revisions before cutover.
#
#   tools/schema_baseline.sh                     # from production, read-only
#   REFERENCE_DATABASE_URL=… tools/schema_baseline.sh
#
# Reads the reference; writes only the local file. The one edit applied is
# stripping psql's `\restrict` / `\unrestrict` guards, which are meta-commands
# psql understands and PDO does not — the migrator executes this file over a
# plain connection, so it has to be pure SQL.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./pg_client.sh
. "$here/pg_client.sh"

REFERENCE_DATABASE_URL="${REFERENCE_DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/book_scraper}"
out="${1:-$here/../schema/0001_baseline.sql}"

echo "reference: $REFERENCE_DATABASE_URL"
echo "client:    $(pg_client_describe) — $(pg_client_version)"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

pg_dump_schema "$REFERENCE_DATABASE_URL" > "$tmp"

{
    cat <<'HDR'
--
-- Migration 0001 — baseline schema.
--
-- GENERATED, NOT WRITTEN. `pg_dump --schema-only` of the catalogue Alembic
-- built, with psql's \restrict guards removed so this is pure SQL. Alembic's
-- 118 revisions are deliberately not re-expressed: a verbatim dump cannot
-- drift from the schema it was dumped from, and hand-translating enums,
-- partial unique indexes and CHECK expressions is where fidelity is lost.
--
-- Regenerate with:  php/tools/schema_baseline.sh
-- Verify with:      make -C php schema-gate
--
HDR
    grep -v '^\\restrict ' "$tmp" | grep -v '^\\unrestrict '
} > "$out"

echo "wrote: $out ($(grep -c '' "$out") lines)"
