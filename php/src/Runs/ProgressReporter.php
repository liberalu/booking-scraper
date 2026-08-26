<?php

declare(strict_types=1);

namespace BookScraper\Runs;

use BookScraper\Models\ScrapeRun;
use Illuminate\Support\Carbon;

/**
 * Writes a run's counters WHILE it runs, not only when it finishes.
 *
 * Without this the three crawl paths each called `RunLifecycle::progress()`
 * exactly once, after the spider closed, so `urls_processed` sat at 0 for the
 * whole run and jumped to the total at the end. On a short crawl nobody
 * notices; on patogupirkti's 50,536-URL rescan the dashboard shows `0/50536`
 * for hours, which reads as a hung run — it sent me looking for a hang that
 * was not there.
 *
 * Every tenth item, which is what the Python pipeline did, for the reason it
 * recorded: small enough that the counter visibly moves on a slow crawl, large
 * enough not to spend the write budget on a `scrape_runs` UPDATE per item.
 *
 * Static because run-scoped state has to be reachable from a roach item
 * processor, which the container builds rather than the caller — the same
 * reason PersistItemProcessor holds its tally statically.
 */
final class ProgressReporter
{
    /** Python's cadence, and its rationale. Not a knob worth exposing. */
    private const EVERY = 10;

    private static ?int $runId = null;

    /** @var (callable(array<string, int>): int)|null */
    private static $processedFrom = null;

    private static int $ticks = 0;

    /**
     * @param callable(array<string, int>): int $processedFrom
     *        How this phase turns its tally into `urls_processed`. Passed in
     *        rather than assumed: discover counts URLs, a serial scan counts
     *        added + updated + non-product + canonical, and a roach scan omits
     *        non-product. Using one formula mid-run and another at the end
     *        would make the number jump backwards when the run closed.
     */
    public static function bind(?int $runId, callable $processedFrom): void
    {
        self::$runId = $runId;
        self::$processedFrom = $processedFrom;
        self::$ticks = 0;
    }

    /** Forget the binding. Only the tests need this. */
    public static function reset(): void
    {
        self::$runId = null;
        self::$processedFrom = null;
        self::$ticks = 0;
    }

    /**
     * One item persisted. Writes on every EVERY-th call.
     *
     * @param array<string, int> $tally
     */
    public static function tick(array $tally): void
    {
        self::$ticks++;
        if (self::$ticks % self::EVERY !== 0) {
            return;
        }
        self::write($tally);
    }

    /**
     * Write regardless of the cadence — for a caller that knows it has
     * finished a unit of work worth showing.
     *
     * @param array<string, int> $tally
     */
    public static function flush(array $tally): void
    {
        self::write($tally);
    }

    /** @param array<string, int> $tally */
    private static function write(array $tally): void
    {
        if (self::$runId === null || self::$processedFrom === null) {
            return;
        }

        // Straight to the row, bypassing the model, exactly as
        // RunLifecycle::progress does — and touching last_heartbeat, because
        // an item persisted is activity.
        ScrapeRun::whereKey(self::$runId)->update([
            'urls_processed' => (self::$processedFrom)($tally),
            'items_added' => $tally['added'] ?? 0,
            'items_updated' => $tally['updated'] ?? 0,
            'error_count' => $tally['failed'] ?? 0,
            'last_heartbeat' => Carbon::now('UTC'),
        ]);
    }
}
