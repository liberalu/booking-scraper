<?php

declare(strict_types=1);

namespace BookScraper\Runs;

use Illuminate\Support\Facades\DB;

/**
 * Boot-time reconciliation and queue inheritance, ported from
 * mark_orphan_runs_failed() and reset_retryable_failures() in
 * book_scraper/db/repo.py.
 */
final class RunReconciler
{
    /**
     * Failure reasons worth retrying on the next attempt.
     *
     * All three are transient by nature: the item was in flight when the
     * process died, timed out mid-processing, or hit a 5xx during page
     * subdivision.
     */
    private const RETRYABLE_REASONS = ['run_aborted', 'stuck_in_processing', 'subdivision_5xx'];

    /**
     * Dispatch attempts after which a failure sticks.
     *
     * Without this ceiling a URL the shop persistently 5xxes gets aborted on
     * every stall (→ run_aborted, retryable), reset to pending, redispatched
     * and re-stalls — never retiring, and starving the healthy backlog behind
     * it. Mirrors the end-of-run retry sweep and the dashboard's "exhausted"
     * display so a URL gives up after the same number of tries either way.
     */
    public const RETRY_CAP = 3;

    /**
     * Fail every run still marked `running`. Call on boot: any such row
     * belongs to a process the restart killed.
     *
     * They are flagged resumable because an orphan had a real crawl doing
     * real work — dropping its pending queue would throw that away.
     *
     * @return list<array{id: int, shop: string, phase: string}>
     */
    public static function markOrphansFailed(): array
    {
        $orphans = DB::table('scrape_runs')
            ->join('shops', 'shops.id', '=', 'scrape_runs.shop_id')
            ->where('scrape_runs.status', 'running')
            ->select('scrape_runs.id', 'shops.name as shop', 'scrape_runs.phase')
            ->get();

        if ($orphans->isEmpty()) {
            return [];
        }

        // Through the shared transition, not a hand-rolled UPDATE: an orphan
        // also needs its in-flight rows aborted and a failure issue recorded,
        // and the copy here used to do neither.
        foreach ($orphans as $orphan) {
            RunFinisher::finish(
                (int) $orphan->id,
                'failed',
                'orphan_on_boot',
                resumableAfterFailure: true,
            );
        }

        return $orphans->map(fn ($row): array => [
            'id' => (int) $row->id,
            'shop' => (string) $row->shop,
            'phase' => (string) $row->phase,
        ])->all();
    }

    /**
     * Return retryable failed items to `pending` so the adopting process
     * picks them up. Items at or past the cap stay failed.
     *
     * Returns the number reset.
     */
    public static function resetRetryableFailures(int $runId, int $cap = self::RETRY_CAP): int
    {
        $ids = DB::table('scrape_url_items')
            ->join(
                'scrape_failures',
                'scrape_failures.scrape_url_item_id',
                '=',
                'scrape_url_items.id'
            )
            ->where('scrape_url_items.run_id', $runId)
            ->where('scrape_url_items.status', 'failed')
            ->where('scrape_url_items.attempts', '<', $cap)
            ->where('scrape_failures.run_id', $runId)
            ->whereIn('scrape_failures.error_reason', self::RETRYABLE_REASONS)
            ->distinct()
            ->pluck('scrape_url_items.id')
            ->all();

        if ($ids === []) {
            return 0;
        }

        return DB::table('scrape_url_items')
            ->whereIn('id', $ids)
            ->update(['status' => 'pending', 'done_at' => null]);
    }

    /**
     * Items left in `processing` by a dead process are unowned; return them
     * to `pending` so the adopting process can claim them.
     */
    public static function releaseStuckProcessing(int $runId): int
    {
        return DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'processing')
            ->update(['status' => 'pending', 'claimed_at' => null]);
    }
}
