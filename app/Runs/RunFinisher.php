<?php

declare(strict_types=1);

namespace App\Runs;

use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * The one fail/complete transition, ported from finish_scrape_run.
 *
 * Four things have to happen together when a run reaches a terminal state:
 * the row transitions, in-flight `processing` items are aborted, a failure
 * gets a `scrape_run_failed` issue so it surfaces on the issues page, and a
 * terminal event lands on the timeline. Upstream had this body hand-rolled in
 * three places and they drifted — the copies only handled `running` runs, so
 * a run failing out of `stopping` left stranded rows and recorded no issue.
 * One implementation, called from everywhere.
 */
final class RunFinisher
{
    /** Every state that still has work to unwind. */
    private const NON_TERMINAL = ['running', 'stopping', 'paused'];

    /**
     * @return bool whether the run existed and was transitioned
     */
    public static function finish(
        int $runId,
        string $status,
        ?string $reason = null,
        bool $resumableAfterFailure = false,
    ): bool {
        return (bool) DB::transaction(function () use (
            $runId,
            $status,
            $reason,
            $resumableAfterFailure
        ): bool {
            $run = DB::table('scrape_runs')->where('id', $runId)->lockForUpdate()->first();
            if ($run === null) {
                return false;
            }
            // Guarded on non-terminal rather than "was running": a run failing
            // out of `stopping` or `paused` still has items to abort and still
            // deserves an issue.
            $wasNonTerminal = in_array($run->status, self::NON_TERMINAL, true);

            $fields = [
                'status' => $status,
                'finished_at' => Carbon::now('UTC'),
            ];
            // First writer wins on close_reason, so a more specific reason
            // recorded earlier is not overwritten by a generic one.
            if ($reason !== null && $run->close_reason === null) {
                $fields['close_reason'] = $reason;
            }
            if ($resumableAfterFailure) {
                $fields['resumable_after_failure'] = true;
            }
            DB::table('scrape_runs')->where('id', $runId)->update($fields);

            if (!$wasNonTerminal) {
                return true;
            }

            self::abortProcessingItems($runId);
            if ($status === 'failed') {
                self::recordFailureIssue($runId, (int) $run->shop_id, $reason ?? 'finished_failed');
            }
            if (in_array($status, ['completed', 'failed'], true)) {
                $fresh = DB::table('scrape_runs')->where('id', $runId)->first();
                RunFailsafe::recordEvent(
                    $runId,
                    $status === 'completed' ? RunEvent::COMPLETED : RunEvent::FAILED,
                    [
                        'close_reason' => $fresh->close_reason ?? null,
                        'urls_processed' => (int) ($fresh->urls_processed ?? 0),
                        'error_count' => (int) ($fresh->error_count ?? 0),
                    ],
                );
            }

            return true;
        });
    }

    /**
     * In-flight rows whose process is gone.
     *
     * `done_at is null` makes a concurrent reaper pass a no-op rather than a
     * double-write.
     */
    public static function abortProcessingItems(int $runId): int
    {
        $items = DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'processing')
            ->whereNull('done_at')
            ->get(['id', 'run_id', 'shop_id', 'url', 'discovered_url_id']);
        if ($items->isEmpty()) {
            return 0;
        }

        $now = Carbon::now('UTC');
        DB::table('scrape_url_items')
            ->whereIn('id', $items->pluck('id')->all())
            ->update(['status' => 'failed', 'done_at' => $now]);

        // The queue row carries `status` only; the reason lives in
        // scrape_failures, which is append-only — that is what makes
        // `run_aborted` a retryable reason the next run can act on.
        DB::table('scrape_failures')->insert($items->map(
            static fn ($item): array => [
                'scrape_url_item_id' => $item->id,
                'run_id' => $item->run_id,
                'shop_id' => $item->shop_id,
                'url' => $item->url,
                'discovered_url_id' => $item->discovered_url_id,
                'occurred_at' => $now,
                'error_reason' => 'run_aborted',
                'http_status' => null,
                'error_detail' => 'run_aborted',
                'lifecycle_state' => 'new',
            ]
        )->all());

        return $items->count();
    }

    /**
     * A failed run gets one issue, so it shows up on the issues page instead
     * of only in the runs list. Idempotent.
     */
    private static function recordFailureIssue(int $runId, int $shopId, string $reason): void
    {
        $existing = DB::table('validation_issues')
            ->where('last_seen_run_id', $runId)
            ->where('issue', 'scrape_run_failed')
            ->exists();
        if ($existing) {
            return;
        }
        DB::table('validation_issues')->insert([
            'last_seen_run_id' => $runId,
            'shop_id' => $shopId,
            'url' => "run:{$runId}",
            'field' => 'run',
            'issue' => 'scrape_run_failed',
            'raw_value' => $reason,
            'lifecycle_state' => 'new',
            'run_count' => 1,
        ]);
    }
}
