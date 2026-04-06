#!/bin/bash
# Watchdog: runs scan script, restarts if stalled.
# Usage: bash book_scraper/scripts/watchdog.sh [shop]
#
# Checks urls_processed every 90s. If no progress, kills and restarts.
# Stops when all URLs are done (exit code 0 from scan script).

SHOP="${1:-vaga}"
STALL_CHECK=90  # seconds between checks
DB_URL="postgresql://postgres:postgres@localhost:5432/book_scraper"
MAX_RESTARTS=50

get_progress() {
    psql -t -A "$DB_URL" \
        -c "SELECT COALESCE(urls_processed, 0) FROM scrape_runs ORDER BY id DESC LIMIT 1" 2>/dev/null
}

echo "=== Watchdog started for shop: $SHOP ==="

for i in $(seq 1 $MAX_RESTARTS); do
    echo ""
    echo "=== Run $i/$MAX_RESTARTS — $(date) ==="

    # Start scan in background
    uv run scrapy crawl scan -a shop="$SHOP" &
    PID=$!

    LAST_PROGRESS=$(get_progress)

    while kill -0 "$PID" 2>/dev/null; do
        sleep "$STALL_CHECK"

        # Check if still running
        if ! kill -0 "$PID" 2>/dev/null; then
            break
        fi

        CURRENT=$(get_progress)
        if [ "$CURRENT" = "$LAST_PROGRESS" ]; then
            echo "STALL DETECTED: progress stuck at $CURRENT for ${STALL_CHECK}s — restarting"
            kill "$PID" 2>/dev/null
            sleep 2
            kill -9 "$PID" 2>/dev/null
            wait "$PID" 2>/dev/null
            sleep 10  # cooldown before restart
            break
        fi
        LAST_PROGRESS="$CURRENT"
        echo "  Progress: $CURRENT (checked at $(date +%H:%M:%S))"
    done

    # Wait for process to finish
    wait "$PID" 2>/dev/null
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        echo "=== Scan completed successfully ==="
        exit 0
    fi

    echo "Exit code: $EXIT_CODE — will restart after cooldown"
    sleep 10
done

echo "=== Max restarts ($MAX_RESTARTS) reached ==="
exit 1
