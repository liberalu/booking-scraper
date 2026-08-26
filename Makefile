# Thin delegator. Everything lives in php/Makefile, which pins the PHP 8.4
# runtime that roach-php requires; these targets exist so `make test` works
# from the repository root.
#
# This file used to hold the Python stack's lint, test, coverage and image
# builds. It went with the stack — see
# docs/superpowers/plans/2026-08-25-python-fixes-and-removal-plan.md.

# OrbStack and Docker Desktop on macOS inject NO_PROXY entries containing IPv6
# CIDR blocks into the build environment, and `apt-get` inside the image build
# cannot reach Debian mirrors through them — it reports "Package X not
# available" and the build succeeds with packages missing. Clearing the vars at
# the target boundary keeps the workaround out of muscle memory. Avoid bare
# `docker compose build`.
CLEAR_PROXY := HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy="" ALL_PROXY="" all_proxy=""

.PHONY: test test-offline lint ci install fixture-db schema-gate \
        compose-build compose-up compose-up-scheduler compose-down compose-logs

## Every suite: library, crawler, dashboard.
## Needs the test cluster: docker compose --profile test up -d postgres-test
test:
	$(MAKE) -C php test-all

## Everything that needs no database.
test-offline:
	$(MAKE) -C php test-offline

lint:
	$(MAKE) -C php lint

ci: lint test

## Composer install for all three projects.
install:
	$(MAKE) -C php install-all

## Rebuild the fixture-only database the frozen API shapes are taken over.
fixture-db:
	$(MAKE) -C php fixture-db

## Does php/schema still reproduce the real catalogue's schema?
schema-gate:
	$(MAKE) -C php schema-gate

## Build the PHP image. Use this, not bare `docker compose build`.
compose-build:
	$(CLEAR_PROXY) docker compose build dashboard

## Bring the stack up WITHOUT the scheduler: database, dashboard, reaper.
## Safe to run any time — nothing starts crawling on its own.
compose-up:
	docker compose up -d postgres dashboard reaper

## Start the scheduler too. THIS STARTS CRAWLING: any schedule whose window
## has passed fires, one per tick, against live shops. After downtime that is
## a backlog — `docker compose run --rm scheduler php artisan runs:schedule
## --dry-run` first to see what it would do.
compose-up-scheduler: compose-up
	docker compose up -d scheduler

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f dashboard scheduler reaper
