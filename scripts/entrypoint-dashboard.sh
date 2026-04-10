#!/bin/bash
set -e

echo "Waiting for database migrations (handled by scraper)..."
sleep 5

echo "Starting dashboard..."
cd /app
exec .venv/bin/uvicorn book_scraper.dashboard.app:app --host 0.0.0.0 --port 8000
