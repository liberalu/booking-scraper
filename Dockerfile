# --- Base stage ---
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra dashboard

# Copy application code
COPY book_scraper/ book_scraper/
COPY scripts/ scripts/
COPY alembic/ alembic/
COPY alembic.ini .
COPY config/ config/
COPY scrapy.cfg .

ENV PYTHONPATH=/app
ENV DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper

# --- Scraper stage ---
FROM base AS scraper

RUN apt-get update && apt-get install -y --no-install-recommends cron logrotate && rm -rf /var/lib/apt/lists/*

# Logrotate config for the JSONL events log (daily, 14-day retention).
# Uses copytruncate so no SIGHUP plumbing is needed.
COPY docker/logrotate.d/scrapy_events /etc/logrotate.d/scrapy_events

COPY scripts/entrypoint-scraper.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]

# --- Dashboard stage ---
FROM base AS dashboard

COPY scripts/entrypoint-dashboard.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

CMD ["/entrypoint.sh"]
