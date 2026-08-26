# roach-php supports PHP <= 8.4; Homebrew's default `php` is 8.5 and
# composer refuses to resolve against it. Pin the runtime here so no
# caller has to remember the PATH dance.
PHP := /opt/homebrew/opt/php@8.4/bin/php
COMPOSER := $(PHP) $(shell which composer)

TEST_DATABASE_URL ?= postgresql://postgres:postgres@localhost:5433/book_scraper_php_test
DATABASE_URL ?= postgresql://postgres:postgres@localhost:5432/book_scraper

.PHONY: install install-all test test-all test-offline parse lint dashboard fixture-db crawl discover validate match reconcile reap migrate migrate-status schema-baseline schema-gate schema-gate-sabotage

install:
	$(COMPOSER) install

## Install all three projects: library, crawler, dashboard.
install-all: install
	cd crawler && $(COMPOSER) install
	cd dashboard && $(COMPOSER) install

## Full suite. Needs the test DB (docker compose up -d postgres-test).
test:
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PHP) vendor/bin/phpunit

## Everything that needs no database.
test-offline:
	$(PHP) vendor/bin/phpunit --exclude-group db --filter 'Parser|UrlUtils|SubSecond'

## Parse a page. No args = the bundled fixture (offline).
##   make parse URL=https://vaga.lt/sirdies-kauleliai
##   make parse FILE=../tests/fixtures/vaga_category_page.html KIND=category
parse:
	$(PHP) bin/parse $(if $(URL),--url=$(URL),) $(if $(FILE),--file=$(FILE),) $(if $(KIND),--kind=$(KIND),)

lint:
	@for f in $$(find src tests -name '*.php'); do $(PHP) -l $$f > /dev/null || exit 1; done
	@echo "lint ok"

## Serve the PHP dashboard on :8002, beside the Python one on :8001.
dashboard:
	cd dashboard && $(PHP) artisan serve --port=8002 --host=127.0.0.1

## Build the fixture-only database the frozen API shapes are taken over.
## Dropped and rebuilt from php/schema's baseline plus SyntheticShop, so it
## needs nothing from the live catalogue.
fixture-db:
	DATABASE_URL=$(TEST_DATABASE_URL) $(PHP) bin/fixture-db --recreate

## Every suite: library, crawler, dashboard. The dashboard's goldens build
## their own fixture-only database, so this needs the test cluster up.
test-all: test
	cd crawler && TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PHP) vendor/bin/phpunit
	cd dashboard && TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PHP) vendor/bin/phpunit

## Scan URLs into the database named by DATABASE_URL.
##   make crawl URLS=https://vaga.lt/some-book
##   make crawl MAX=50
##   make crawl MAX=5 ARGS=--dry-run
crawl:
	cd crawler && DATABASE_URL="$(DATABASE_URL)" $(PHP) bin/crawl scan --shop=$(or $(SHOP),vaga) \
		$(if $(URLS),--urls=$(URLS),) $(if $(MAX),--max-urls=$(MAX),) $(ARGS)

## Find URLs. PAGES caps pages per seed.
##   make discover STRATEGY=sitemap
##   make discover STRATEGY=categories PAGES=3
##   make discover SHOP=pegasas STRATEGY=graphql PAGES=1
##   make discover SHOP=pegasas STRATEGY=lupasearch PAGES=1
##   make discover SHOP=ibiblioteka STRATEGY=ibiblioteka_api ARGS=--max-bands=2
discover:
	cd crawler && DATABASE_URL="$(DATABASE_URL)" $(PHP) bin/crawl discover --shop=$(or $(SHOP),vaga) \
		--strategy=$(or $(STRATEGY),sitemap) $(if $(PAGES),--max-pages=$(PAGES),) $(ARGS)

## Fail runs left `running` by a killed process. Call on boot.
reconcile:
	cd crawler && DATABASE_URL="$(DATABASE_URL)" $(PHP) bin/crawl reconcile

## Run the match phase (steps 1 + 2; SYNTHESIS=1 adds step 3).
##   make match SHOP=vaga
##   make match SHOP=vaga SYNTHESIS=1
match:
	cd crawler && DATABASE_URL="$(DATABASE_URL)" $(PHP) bin/match --shop=$(or $(SHOP),vaga) \
		$(if $(SYNTHESIS),--synthesis,)

## Run the data-quality validator. Writes to DATABASE_URL.
##   make validate SHOP=vaga
validate:
	cd crawler && DATABASE_URL="$(DATABASE_URL)" $(PHP) bin/validate --shop=$(or $(SHOP),vaga)

## Fail runs whose process died. Nothing else does this — run it on a timer.
##   make reap                 one sweep
##   make reap ARGS=--watch    keep sweeping
reap:
	cd dashboard && $(PHP) artisan runs:reap $(ARGS)

## ---------------------------------------------------------------------------
## Schema (phase 1 of removing Python)
##
## Alembic still owns the production catalogue. These targets give PHP its own
## baseline and prove it faithful; they never write to port 5432.
## ---------------------------------------------------------------------------

## Apply the PHP migrations to a database you name. No default target —
## config/default.toml's [database].url is production.
##   make migrate MIGRATE_DATABASE_URL=postgresql://...:5433/somedb
migrate:
	$(PHP) bin/migrate apply --database="$(or $(MIGRATE_DATABASE_URL),$(error set MIGRATE_DATABASE_URL))" $(ARGS)

migrate-status:
	$(PHP) bin/migrate status --database="$(or $(MIGRATE_DATABASE_URL),$(error set MIGRATE_DATABASE_URL))"

## Re-dump schema/0001_baseline.sql from the reference database. Reads only.
## Run this if Alembic gains revisions before cutover.
schema-baseline:
	./tools/schema_baseline.sh

## THE GATE. Fresh database on the test cluster from the PHP baseline,
## pg_dump --schema-only both sides, normalise, diff. Non-zero on any
## difference — this is what catches enums, partial unique indexes, CHECK
## expressions and FK actions.
schema-gate:
	./tools/schema_gate.sh

## Prove the gate can fail: drop a unique index from a COPY of the baseline
## and require a non-zero exit that names it.
schema-gate-sabotage:
	./tools/schema_gate_sabotage.sh
