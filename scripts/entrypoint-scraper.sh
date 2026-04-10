#!/bin/bash
set -e

echo "Running database migrations..."
cd /app
PYTHONPATH=. .venv/bin/python -m alembic upgrade head

echo "Installing crontab..."
crontab /app/cron/scraper-crontab

echo "Starting cron..."
touch /var/log/scraper.log
exec cron -f
