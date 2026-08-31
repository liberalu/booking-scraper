#!/usr/bin/env bash

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
app_root="$(cd "$here/.." && pwd)"
. "$here/pg_client.sh"

PHP_BIN="${PHP_BIN:-/opt/homebrew/opt/php@8.4/bin/php}"
REFERENCE_DATABASE_URL="${REFERENCE_DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/book_scraper}"
SCRATCH_CLUSTER_URL="${SCRATCH_CLUSTER_URL:-postgresql://postgres:postgres@localhost:5433/postgres}"
SCRATCH_DB="${SCRATCH_DB:-bs_schema_gate_$$}"

pg_parse_dsn "$SCRATCH_CLUSTER_URL"
scratch_port="$PGD_PORT"
scratch_host="$PGD_HOST"
scratch_user="$PGD_USER"
scratch_pass="$PGD_PASS"

if [ "$scratch_port" = "5432" ]; then
    echo "schema-gate: refusing to create a scratch database on port 5432 (production)." >&2
    echo "  Point SCRATCH_CLUSTER_URL at the test cluster (5433)." >&2
    exit 2
fi

pg_parse_dsn "$REFERENCE_DATABASE_URL"
if [ "$PGD_HOST:$PGD_PORT" = "$scratch_host:$scratch_port" ] && [ "$PGD_NAME" = "$SCRATCH_DB" ]; then
    echo "schema-gate: reference and scratch are the same database." >&2
    exit 2
fi

scratch_url="postgresql://${scratch_user}:${scratch_pass}@${scratch_host}:${scratch_port}/${SCRATCH_DB}"
work="$(mktemp -d)"

cleanup() {
    pg_psql "$SCRATCH_CLUSTER_URL" -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\"" > /dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT

echo "reference:  $REFERENCE_DATABASE_URL  (read-only)"
echo "scratch:    $scratch_host:$scratch_port/$SCRATCH_DB"
echo "migrations: ${SCHEMA_MIGRATIONS_DIR:-$app_root/database/schema}"
echo "client:     $(pg_client_describe) — $(pg_client_version)"
echo

pg_psql "$SCRATCH_CLUSTER_URL" -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\"" > /dev/null
pg_psql "$SCRATCH_CLUSTER_URL" -c "CREATE DATABASE \"$SCRATCH_DB\"" > /dev/null

"$PHP_BIN" "$app_root/bin/migrate" apply --database="$scratch_url" \
    ${SCHEMA_MIGRATIONS_DIR:+--dir="$SCHEMA_MIGRATIONS_DIR"}

dump() {
    pg_dump_schema "$1" --exclude-table=public.php_schema_migrations \
        | "$here/schema_normalize.sh"
}

dump "$REFERENCE_DATABASE_URL" > "$work/reference.sql"
dump "$scratch_url" > "$work/php.sql"

echo
if diff -u "$work/reference.sql" "$work/php.sql" > "$work/diff.txt"; then
    printf 'schema-gate: PASS — %s lines identical (%s tables, %s enums, %s unique indexes, %s check constraints)\n' \
        "$(grep -c '' "$work/reference.sql")" \
        "$(grep -c '^CREATE TABLE' "$work/reference.sql")" \
        "$(grep -c '^CREATE TYPE' "$work/reference.sql")" \
        "$(grep -c '^CREATE UNIQUE INDEX' "$work/reference.sql")" \
        "$(grep -c 'CONSTRAINT ck_' "$work/reference.sql")"
    exit 0
fi

echo "schema-gate: FAIL — the PHP baseline does not reproduce the reference schema."
echo "  - reference, + PHP baseline"
echo
cat "$work/diff.txt"
echo
echo "schema-gate: FAIL ($(( $(grep -c '^[-+]' "$work/diff.txt") - 2 )) differing lines)"
exit 1
