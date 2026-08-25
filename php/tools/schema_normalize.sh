#!/usr/bin/env bash
#
# Canonicalise a `pg_dump --schema-only` dump so two dumps of the SAME schema
# compare equal. stdin -> stdout.
#
# Three rules, and only three. Every one of them was arrived at by taking two
# dumps of a schema known to be identical and looking at what actually
# differed; nothing here is defensive. A blanket "strip anything that looks
# like a cast" would make the gate stop catching real type changes, which is
# most of what it exists to catch.
#
#   1. psql backslash meta-commands (`\restrict` / `\unrestrict`) carry a
#      random per-invocation token and no schema information at all.
#
#   2. The "Dumped from database version" / "Dumped by pg_dump version"
#      header comments. The gate prints the client version it used; a version
#      skew that actually changes the schema output still shows up as a diff
#      in the body.
#
#   3. One CHECK constraint that Postgres deparses two equivalent ways.
#      SQLAlchemy emits the array cast outside the ARRAY constructor; once
#      the constraint has been through a restore, Postgres re-renders it with
#      the cast on each element:
#
#        = ANY ((ARRAY['a'::character varying, 'b'::character varying])::text[])
#        = ANY (ARRAY[('a'::character varying)::text, ('b'::character varying)::text])
#
#      Same values, same semantics, and the difference is permanent — the
#      baseline is a restored dump by construction. Both forms are folded to
#      `ANY (ARRAY['a'::character varying, ...])`.
#
#      The two substitutions are pinned to those exact shapes: the outer one
#      only strips `::text[]` applied to an ARRAY inside `ANY (…)`, and the
#      inner one only strips `::text` re-applied to an already-cast
#      `character varying` literal. A change to the element type, the target
#      type, or the value list survives both and fails the gate.

set -euo pipefail

sed \
    -e '/^\\restrict /d' \
    -e '/^\\unrestrict /d' \
    -e '/^-- Dumped from database version /d' \
    -e '/^-- Dumped by pg_dump version /d' \
    -e 's/ANY ((ARRAY\[\(.*\)\])::text\[\])/ANY (ARRAY[\1])/g' \
    -e "s/('\([^']*\)'::character varying)::text/'\1'::character varying/g"
