#!/usr/bin/env bash

set -euo pipefail

sed \
    -e '/^\\restrict /d' \
    -e '/^\\unrestrict /d' \
    -e '/^-- Dumped from database version /d' \
    -e '/^-- Dumped by pg_dump version /d' \
    -e 's/ANY ((ARRAY\[\(.*\)\])::text\[\])/ANY (ARRAY[\1])/g' \
    -e "s/('\([^']*\)'::character varying)::text/'\1'::character varying/g"
