FROM python:3.14-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy source
COPY book_scraper/ book_scraper/
COPY config/ config/
COPY alembic/ alembic/
COPY alembic.ini ./

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Health check — exits 1 if scan stalled for 2 minutes
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=30s \
    CMD uv run python book_scraper/scripts/healthcheck.py
