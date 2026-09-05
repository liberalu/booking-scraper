PHP := /opt/homebrew/opt/php@8.4/bin/php
COMPOSER := $(PHP) $(shell which composer)

CLEAR_PROXY := HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy="" ALL_PROXY="" all_proxy=""

TEST_DATABASE_URL ?= postgresql://postgres:postgres@localhost:5433/book_scraper_php_test
DATABASE_URL ?= postgresql://postgres:postgres@localhost:5432/book_scraper

.PHONY: compose-build compose-up compose-up-scheduler compose-down compose-logs frontend \
        cache-check ci install test test-schema test-offline parse syntax lint dashboard fixture-db crawl discover validate match reconcile reap migrate migrate-status schema-baseline schema-gate schema-gate-sabotage

install:
	$(COMPOSER) install

test-schema:
	DATABASE_URL=$(TEST_DATABASE_URL) $(PHP) bin/migrate apply

test: test-schema
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PHP) vendor/bin/phpunit

test-offline:
	$(PHP) vendor/bin/phpunit --exclude-group db --filter 'Parser|UrlUtils|SubSecond'

parse:
	$(PHP) artisan crawler:parse $(if $(URL),--url=$(URL),) $(if $(FILE),--file=$(FILE),) $(if $(KIND),--kind=$(KIND),)

syntax:
	@for f in $$(find app bootstrap config database routes tests -name '*.php') bin/*; do \
		$(PHP) -l $$f > /dev/null || exit 1; done
	@echo "syntax ok"

cache-check:
	$(PHP) artisan config:cache --no-ansi
	$(PHP) artisan route:cache --no-ansi
	$(PHP) artisan optimize:clear --no-ansi

lint: syntax cache-check
	$(COMPOSER) lint
	npm run lint
	npm run format:check
	npm test

frontend:
	npm run build

ci: lint test

dashboard:
	$(PHP) artisan serve --port=8002 --host=127.0.0.1

fixture-db:
	DATABASE_URL=$(TEST_DATABASE_URL) $(PHP) bin/fixture-db --recreate

crawl:
	DATABASE_URL="$(DATABASE_URL)" $(PHP) artisan crawler:run scan --shop=$(or $(SHOP),vaga) \
		$(if $(URLS),--urls=$(URLS),) $(if $(MAX),--max-urls=$(MAX),) $(ARGS)

discover:
	DATABASE_URL="$(DATABASE_URL)" $(PHP) artisan crawler:run discover --shop=$(or $(SHOP),vaga) \
		--strategy=$(or $(STRATEGY),sitemap) $(if $(PAGES),--max-pages=$(PAGES),) $(ARGS)

reconcile:
	DATABASE_URL="$(DATABASE_URL)" $(PHP) artisan crawler:run reconcile

match:
	DATABASE_URL="$(DATABASE_URL)" $(PHP) artisan books:match --shop=$(or $(SHOP),vaga) \
		$(if $(SYNTHESIS),--synthesis,)

validate:
	DATABASE_URL="$(DATABASE_URL)" $(PHP) artisan books:validate --shop=$(or $(SHOP),vaga)

reap:
	$(PHP) artisan runs:reap $(ARGS)


migrate:
	$(PHP) bin/migrate apply --database="$(or $(MIGRATE_DATABASE_URL),$(error set MIGRATE_DATABASE_URL))" $(ARGS)

migrate-status:
	$(PHP) bin/migrate status --database="$(or $(MIGRATE_DATABASE_URL),$(error set MIGRATE_DATABASE_URL))"

schema-baseline:
	./tools/schema_baseline.sh

schema-gate:
	./tools/schema_gate.sh

schema-gate-sabotage:
	./tools/schema_gate_sabotage.sh


compose-build:
	$(CLEAR_PROXY) docker compose build

compose-up:
	docker compose up -d postgres dashboard reaper

compose-up-scheduler: compose-up
	docker compose up -d scheduler

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f dashboard scheduler reaper
