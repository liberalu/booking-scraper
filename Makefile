.PHONY: lint format test build compose-build compose-build-scraper compose-build-dashboard ci crawl coverage coverage-html audit deps

IMAGE_NAME ?= book-scraper
IMAGE_TAG  ?= latest

# OrbStack / Docker Desktop on macOS inject NO_PROXY entries containing IPv6
# CIDR blocks. These poison the build context — `apt-get` inside the image
# build cannot reach Debian mirrors and silently reports "Package X not
# available" (see CLAUDE.md "OrbStack build gotcha"). Clearing the vars at
# the make-target boundary keeps the workaround out of muscle memory.
CLEAR_PROXY := HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy="" ALL_PROXY="" all_proxy=""

lint:
	uv run ruff check book_scraper/ tests/
	uv run ruff format --check book_scraper/ tests/
	uv run mypy book_scraper/

format:
	uv run ruff format book_scraper/ tests/
	uv run ruff check --fix book_scraper/ tests/

test:
	uv run pytest -v

build:
	$(CLEAR_PROXY) docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

# Always use these for `docker compose build`. Bare `docker compose build`
# silently fails on `apt-get install` inside the scraper image when the
# OrbStack proxy vars are present.
compose-build:
	$(CLEAR_PROXY) docker compose build

compose-build-scraper:
	$(CLEAR_PROXY) docker compose build scraper

compose-build-dashboard:
	$(CLEAR_PROXY) docker compose build dashboard

ci: lint test deps

crawl:
	uv run scrapy crawl $(ARGS)

coverage:
	uv run pytest --cov=book_scraper --cov-report=term-missing -v

coverage-html:
	uv run pytest --cov=book_scraper --cov-report=html
	@echo "Open htmlcov/index.html in your browser"

audit:
	uv run pip-audit

deps:
	uv run deptry book_scraper/
