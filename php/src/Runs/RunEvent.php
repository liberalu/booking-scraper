<?php

declare(strict_types=1);

namespace BookScraper\Runs;

/**
 * Event types for the scrape_run_events lifecycle log, mirroring
 * book_scraper/db/scrape_run_events.py.
 */
final class RunEvent
{
    public const STARTED = 'started';
    public const PAUSED = 'paused';
    public const RESUMED = 'resumed';
    public const STOP_REQUESTED = 'stop_requested';
    public const RETRY_FAILURES = 'retry_failures';
    public const RERUN = 'rerun';
    public const CONTINUED = 'continued';
    public const RESUMED_AFTER_FAILURE = 'resumed_after_failure';
    public const COMPLETED = 'completed';
    public const FAILED = 'failed';
    public const SUBDIVIDED = 'subdivided';

    /**
     * Single-row restart marker, emitted on the SAME logical-run row each
     * time a process restart happens (stall, heartbeat timeout, boot
     * reconcile). Distinct from RESUMED_AFTER_FAILURE, which belonged to
     * the older model that created a child row per attempt.
     */
    public const RESTARTED = 'restarted';

    public const CHAIN_SKIPPED = 'chain_skipped';

    public const ACTOR_OPERATOR = 'operator';
    public const ACTOR_SYSTEM = 'system';

    public const ALL = [
        self::STARTED, self::PAUSED, self::RESUMED, self::STOP_REQUESTED,
        self::RETRY_FAILURES, self::RERUN, self::CONTINUED,
        self::RESUMED_AFTER_FAILURE, self::RESTARTED, self::COMPLETED,
        self::FAILED, self::SUBDIVIDED, self::CHAIN_SKIPPED,
    ];
}
