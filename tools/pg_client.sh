#!/usr/bin/env bash
# Shared `psql` / `pg_dump` runner for the schema tooling. Sourced, not run.
#
# Neither binary is on this machine's PATH — both Postgres clusters are
# containers (postgres:16) and no libpq was ever installed on the host. So
# rather than making the schema gate depend on a client nobody has, this
# resolves one of three runners, in order:
#
#   1. `pg_dump` on PATH, if a future machine has one.
#   2. `docker exec` into a running postgres container (default: the test
#      cluster's own container, which is where the scratch database lives).
#   3. `docker run --rm postgres:16`, so the gate still works with the
#      compose stack down.
#
# Cases 2 and 3 talk to the host's published ports, so `localhost` in a DSN
# is rewritten to `host.docker.internal` before it crosses into a container.
# Deliberately NOT the compose service names: the DSNs in this repo are
# host-side (5432 / 5433), and translating ports to service names would
# guess which cluster is meant.

set -euo pipefail

PG_IMAGE="${PG_IMAGE:-postgres:16}"
PG_CLIENT_CONTAINER="${PG_CLIENT_CONTAINER:-book-scraper-postgres-test-1}"

_pg_runner=""

pg_client_runner() {
    if [ -n "$_pg_runner" ]; then
        printf '%s' "$_pg_runner"
        return
    fi

    if command -v pg_dump > /dev/null 2>&1 && command -v psql > /dev/null 2>&1; then
        _pg_runner="host"
    elif command -v docker > /dev/null 2>&1 \
        && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$PG_CLIENT_CONTAINER"; then
        _pg_runner="exec"
    elif command -v docker > /dev/null 2>&1; then
        _pg_runner="run"
    else
        echo "pg_client: no psql/pg_dump on PATH and no docker to borrow one from" >&2
        return 1
    fi

    printf '%s' "$_pg_runner"
}

pg_client_describe() {
    case "$(pg_client_runner)" in
        host) echo "host PATH" ;;
        exec) echo "docker exec $PG_CLIENT_CONTAINER" ;;
        run) echo "docker run --rm $PG_IMAGE" ;;
    esac
}

# ---------------------------------------------------------------------------
# DSN parsing. Accepts libpq URLs and the SQLAlchemy-style driver suffix
# (`postgresql+psycopg2://`) so the same value works for both stacks.
# Sets PGD_HOST PGD_PORT PGD_USER PGD_PASS PGD_NAME.
# ---------------------------------------------------------------------------
pg_parse_dsn() {
    local dsn="$1"
    local rest

    rest="${dsn#*://}"
    if [ "$rest" = "$dsn" ]; then
        echo "pg_client: not a postgres URL: $dsn" >&2
        return 1
    fi

    local userinfo="" hostpart
    case "$rest" in
        *@*)
            userinfo="${rest%%@*}"
            hostpart="${rest#*@}"
            ;;
        *) hostpart="$rest" ;;
    esac

    PGD_USER="${userinfo%%:*}"
    PGD_PASS=""
    case "$userinfo" in
        *:*) PGD_PASS="${userinfo#*:}" ;;
    esac
    [ -n "$PGD_USER" ] || PGD_USER="postgres"

    PGD_NAME="${hostpart#*/}"
    PGD_NAME="${PGD_NAME%%\?*}"
    local authority="${hostpart%%/*}"
    PGD_HOST="${authority%%:*}"
    PGD_PORT="5432"
    case "$authority" in
        *:*) PGD_PORT="${authority#*:}" ;;
    esac

    if [ -z "$PGD_NAME" ] || [ "$PGD_NAME" = "$hostpart" ]; then
        echo "pg_client: no database name in DSN: $dsn" >&2
        return 1
    fi
}

# The host as seen from wherever the client actually runs.
_pg_reachable_host() {
    local host="$1"
    if [ "$(pg_client_runner)" = "host" ]; then
        printf '%s' "$host"
        return
    fi
    case "$host" in
        localhost | 127.0.0.1 | ::1) printf 'host.docker.internal' ;;
        *) printf '%s' "$host" ;;
    esac
}

# pg_run <dsn> <binary> [args...]  — stdin is forwarded.
#
# NOTICE is suppressed (WARNING and above still print): `DROP DATABASE IF
# EXISTS` on a database that isn't there is normal operation for the gate, and
# a line of noise per run trains people to skim past this output.
PG_OPTS='-c client_min_messages=warning'

pg_run() {
    local dsn="$1" bin="$2"
    shift 2
    pg_parse_dsn "$dsn"
    local host
    host="$(_pg_reachable_host "$PGD_HOST")"

    case "$(pg_client_runner)" in
        host)
            PGPASSWORD="$PGD_PASS" PGOPTIONS="$PG_OPTS" "$bin" \
                -h "$host" -p "$PGD_PORT" -U "$PGD_USER" -d "$PGD_NAME" "$@"
            ;;
        exec)
            docker exec -i -e "PGPASSWORD=$PGD_PASS" -e "PGOPTIONS=$PG_OPTS" \
                "$PG_CLIENT_CONTAINER" "$bin" \
                -h "$host" -p "$PGD_PORT" -U "$PGD_USER" -d "$PGD_NAME" "$@"
            ;;
        run)
            docker run --rm -i --add-host=host.docker.internal:host-gateway \
                -e "PGPASSWORD=$PGD_PASS" -e "PGOPTIONS=$PG_OPTS" \
                --entrypoint "$bin" "$PG_IMAGE" \
                -h "$host" -p "$PGD_PORT" -U "$PGD_USER" -d "$PGD_NAME" "$@"
            ;;
    esac
}

pg_psql() { local dsn="$1"; shift; pg_run "$dsn" psql -v ON_ERROR_STOP=1 -q "$@"; }

# Schema-only dump, with the flags that make it restorable into a database
# owned by somebody else. No --no-comments: a column comment is schema.
pg_dump_schema() {
    local dsn="$1"
    shift
    pg_run "$dsn" pg_dump --schema-only --no-owner --no-privileges --no-tablespaces "$@"
}

pg_client_version() {
    case "$(pg_client_runner)" in
        host) pg_dump --version ;;
        exec) docker exec "$PG_CLIENT_CONTAINER" pg_dump --version ;;
        run) docker run --rm --entrypoint pg_dump "$PG_IMAGE" --version ;;
    esac
}
