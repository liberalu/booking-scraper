<?php

declare(strict_types=1);

namespace App\Runs;

use Illuminate\Support\Facades\DB;

/**
 * Decides whether a failed run may restart itself, ported from the
 * auto-resume logic in book_scraper/extensions.py.
 *
 * Two independent brakes, because a depth cap alone is not enough:
 *
 *  - **Depth cap** stops a runaway loop.
 *  - **Zero-progress circuit breaker** stops a *structural* bug from
 *    burning the whole depth budget. Patogupirkti runs 363→364→365 all
 *    died at heartbeat_timeout with urls_processed=0, because the queue
 *    size starved the reactor before any fetch landed. The cap allowed
 *    three attempts at a bug that could never succeed; this fires after
 *    two, so the operator sees the signal sooner.
 */
final class ResumePolicy
{
    /**
     * Consecutive zero-progress restarts before giving up. Deliberately
     * lower than the depth cap so the structural-bug signal surfaces first.
     */
    private const ZERO_PROGRESS_THRESHOLD = 2;

    /** How far back to walk restart events when measuring the streak. */
    private const MAX_LOOKBACK = 8;

    public function __construct(private readonly int $maxAttempts) {}

    /**
     * @return array{allowed: bool, attempt: int, reason: string}
     */
    public function evaluate(int $runId): array
    {
        if ($this->maxAttempts <= 0) {
            return ['allowed' => false, 'attempt' => 0, 'reason' => 'auto-resume disabled'];
        }

        $depth = self::chainDepth($runId);
        $zeroProgress = self::consecutiveZeroProgress($runId);

        if ($zeroProgress >= self::ZERO_PROGRESS_THRESHOLD) {
            return [
                'allowed' => false,
                'attempt' => $depth,
                'reason' => sprintf(
                    '%d consecutive zero-progress restarts (threshold %d) — the bug is '
                    . 'structural, an operator must diagnose before continuing',
                    $zeroProgress,
                    self::ZERO_PROGRESS_THRESHOLD
                ),
            ];
        }

        if ($depth >= $this->maxAttempts) {
            return [
                'allowed' => false,
                'attempt' => $depth,
                'reason' => sprintf(
                    'auto-resume cap reached (depth %d, max %d) — operator can Continue '
                    . 'from the dashboard',
                    $depth,
                    $this->maxAttempts
                ),
            ];
        }

        return [
            'allowed' => true,
            'attempt' => $depth + 1,
            'reason' => sprintf('attempt %d/%d', $depth + 1, $this->maxAttempts),
        ];
    }

    /** Restart events recorded on this run. 0 for a run that never restarted. */
    public static function chainDepth(int $runId): int
    {
        return DB::table('scrape_run_events')
            ->where('run_id', $runId)
            ->where('event_type', RunEvent::RESTARTED)
            ->count();
    }

    /**
     * Trailing restarts that achieved nothing.
     *
     * Each restart event carries `urls_processed_snapshot`. When two
     * consecutive snapshots are equal, nothing happened between the two
     * attempts. Walks newest → oldest and stops at the first restart that
     * did make progress.
     */
    public static function consecutiveZeroProgress(int $runId): int
    {
        $events = DB::table('scrape_run_events')
            ->where('run_id', $runId)
            ->where('event_type', RunEvent::RESTARTED)
            ->orderByDesc('id')
            ->limit(self::MAX_LOOKBACK)
            ->pluck('payload')
            ->all();

        if (count($events) < 2) {
            return 0;
        }

        $snapshots = array_map(
            static function (mixed $payload): ?int {
                $decoded = is_string($payload) ? json_decode($payload, true) : $payload;
                $value = is_array($decoded) ? ($decoded['urls_processed_snapshot'] ?? null) : null;

                return is_numeric($value) ? (int) $value : null;
            },
            $events
        );

        $streak = 0;
        for ($i = 0; $i < count($snapshots) - 1; $i++) {
            [$newer, $older] = [$snapshots[$i], $snapshots[$i + 1]];
            if ($newer === null || $older === null || $newer !== $older) {
                break;
            }
            $streak++;
        }

        return $streak;
    }

    /**
     * The run whose queue a new process should adopt, or null.
     *
     * Resumable means it has pending items AND either it is still active
     * (running/paused own their queue) or it failed with
     * `resumable_after_failure` — reaped for heartbeat or stall timeout,
     * where the queued work was perfectly good.
     */
    public static function findResumable(int $shopId, string $phase): ?object
    {
        return DB::table('scrape_runs')
            ->where('shop_id', $shopId)
            ->where('phase', $phase)
            ->where(function ($query): void {
                $query->whereIn('status', ['running', 'paused'])
                    ->orWhere(function ($inner): void {
                        $inner->where('status', 'failed')
                            ->where('resumable_after_failure', true);
                    });
            })
            ->whereExists(function ($query): void {
                $query->select(DB::raw(1))
                    ->from('scrape_url_items')
                    ->whereColumn('scrape_url_items.run_id', 'scrape_runs.id')
                    ->where('scrape_url_items.status', 'pending');
            })
            ->orderByDesc('started_at')
            ->first();
    }
}
