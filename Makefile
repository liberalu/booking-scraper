# Thin delegator. Everything lives in php/Makefile, which pins the PHP 8.4
# runtime that roach-php requires; these targets exist so `make test` works
# from the repository root.
#
# This file used to hold the Python stack's lint, test, coverage and image
# builds. It went with the stack — see
# docs/superpowers/plans/2026-08-25-python-fixes-and-removal-plan.md.

.PHONY: test test-offline lint ci install fixture-db schema-gate

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
