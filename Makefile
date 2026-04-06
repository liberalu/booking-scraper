.PHONY: lint format test build ci crawl coverage coverage-html audit deps

IMAGE_NAME ?= book-scraper
IMAGE_TAG  ?= latest

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
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

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
