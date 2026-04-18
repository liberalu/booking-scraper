#!/bin/bash
set -e

echo "Running database migrations..."
cd /app
PYTHONPATH=. .venv/bin/python -m alembic upgrade head

echo "Reconciling orphan scrape runs..."
PYTHONPATH=. .venv/bin/python -m book_scraper.scripts.reconcile_runs

echo "Generating crontab from cron_jobs table..."
PYTHONPATH=. .venv/bin/python /app/scripts/generate_crontab.py

echo "Starting cron..."
touch /var/log/scraper.log
exec cron -f
