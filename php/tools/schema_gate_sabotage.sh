#!/usr/bin/env bash
#
# Prove the schema gate can fail.
#
# A gate that cannot fail proves nothing, and this repo has been caught by
# exactly that twice — a test asserting `"price" in row` passed while every
# price was None, and `sku_duplicate` looked covered because the test schema
# was missing the partial unique index production has. So: copy the baseline,
# delete one unique index from the copy, run the gate against the copy, and
# require it to fail AND to name the index it lost.
#
# The index removed is `uq_shop_books_shop_sku` on purpose — that is the one
# whose absence from the model made a dead validator check look alive.
#
# Nothing is written to the checked-in baseline: the copy lives in a temp
# directory that goes away with the script.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
php_root="$(cd "$here/.." && pwd)"

VICTIM="${VICTIM:-uq_shop_books_shop_sku}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/schema"
grep -v "CREATE UNIQUE INDEX $VICTIM " "$php_root/schema/0001_baseline.sql" \
    > "$work/schema/0001_baseline.sql"

removed=$((
    $(grep -c '' "$php_root/schema/0001_baseline.sql") -
    $(grep -c '' "$work/schema/0001_baseline.sql")
))
if [ "$removed" -ne 1 ]; then
    echo "sabotage: expected to remove exactly 1 line for $VICTIM, removed $removed" >&2
    exit 2
fi

echo "sabotage: dropped CREATE UNIQUE INDEX $VICTIM from a copy of the baseline"
echo

set +e
SCHEMA_MIGRATIONS_DIR="$work/schema" SCRATCH_DB="bs_schema_gate_sabotage_$$" \
    "$here/schema_gate.sh" > "$work/out.txt" 2>&1
rc=$?
set -e

cat "$work/out.txt"
echo

if [ "$rc" -eq 0 ]; then
    echo "sabotage: FAIL — the gate passed a baseline missing $VICTIM. The gate is blind." >&2
    exit 1
fi

if ! grep -q "$VICTIM" "$work/out.txt"; then
    echo "sabotage: FAIL — the gate failed (exit $rc) but never named $VICTIM." >&2
    exit 1
fi

echo "sabotage: PASS — gate exited $rc and named $VICTIM:"
grep -- "$VICTIM" "$work/out.txt" | sed 's/^/    /'
