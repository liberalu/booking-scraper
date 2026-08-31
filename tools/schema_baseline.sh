#!/usr/bin/env bash

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/pg_client.sh"

REFERENCE_DATABASE_URL="${REFERENCE_DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/book_scraper}"
out="${1:-$here/../database/schema/0001_baseline.sql}"

echo "reference: $REFERENCE_DATABASE_URL"
echo "client:    $(pg_client_describe) — $(pg_client_version)"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

pg_dump_schema "$REFERENCE_DATABASE_URL" > "$tmp"

grep -v '^\\restrict ' "$tmp" | grep -v '^\\unrestrict ' > "$out"

echo "wrote: $out ($(grep -c '' "$out") lines)"
