<?php

declare(strict_types=1);

namespace BookScraper\Runs;

use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * Fails runs whose process is gone, ported from mark_stale_runs.
 *
 * A crawl that dies without unwinding leaves its row `running` forever: the
 * runs list shows it as live, and the shop+phase preflight refuses to start a
 * replacement because "a run is already running". Nothing else notices — the
 * spider that would have finished the row is the thing that died. So this has
 * to come from outside the crawl.
 *
 * `paused` is deliberately not reaped: the heartbeat keeps ticking through a
 * pause, so a paused run never looks stale, and treating it as dead would
 * kill a run an operator deliberately held.
 */
final class Reaper
{
    /**
     * How long without a heartbeat before a run is presumed dead.
     *
     * The live view's freshness window is ~30s; this waits past that so
     * ordinary tick jitter doesn't reap a healthy run.
     */
    public const DEAD_RUN_SECONDS = 60;

    /**
     * Per-row staleness for `processing` items on runs that are still alive.
     * Higher than the dashboard's own "stuck" label (30s) so a row is never
     * reaped before it is even shown as stuck.
     */
    public const STUCK_ROW_THRESHOLD_S = 120;

    /**
     * @return list<array{run_id: int, shop: string, phase: string, close_reason: string}>
     *         one entry per run killed
     */
    public static function sweep(): array
    {
        $cutoff = Carbon::now('UTC')->subSeconds(self::DEAD_RUN_SECONDS);

        $candidates = DB::table('scrape_runs')
            ->join('shops', 'shops.id', '=', 'scrape_runs.shop_id')
            ->whereIn('scrape_runs.status', ['running', 'stopping'])
            ->get([
                'scrape_runs.id',
                'scrape_runs.status',
                'scrape_runs.last_heartbeat',
                'scrape_runs.started_at',
                'scrape_runs.phase',
                'shops.name as shop',
            ]);

        $killed = [];
        foreach ($candidates as $run) {
            $lastActivity = $run->last_heartbeat ?? $run->started_at;
            if ($lastActivity === null || Carbon::parse($lastActivity)->gte($cutoff)) {
                continue;
            }
            // `stopping` means the spider saw the stop request but its close
            // callback never ran — worth distinguishing in the postmortem
            // from a run that simply went silent.
            $reason = $run->status === 'stopping' ? 'stop_timeout' : 'heartbeat_timeout';
            // Reaped runs still own valid pending items, so the next run
            // should adopt them rather than start over.
            RunFinisher::finish((int) $run->id, 'failed', $reason, resumableAfterFailure: true);
            $killed[] = [
                'run_id' => (int) $run->id,
                'shop' => (string) $run->shop,
                'phase' => (string) $run->phase,
                'close_reason' => $reason,
            ];
        }

        self::sweepOrphanedProcessingItems();

        return $killed;
    }

    /**
     * Stale `processing` rows, in two cases.
     *
     * On a terminal run every such row is dead by definition. On a live run
     * only rows claimed longer ago than the threshold are — those are hung
     * workers, and surfacing them in the Failures card beats leaving them at
     * `processing` forever. A row never legitimately claimed
     * (`claimed_at is null`) is never reaped.
     */
    public static function sweepOrphanedProcessingItems(): int
    {
        // Not "completed or failed": `stopping` counts too. A run mid-stop
        // whose process died leaves the same orphaned rows, and excluding it
        // is how they'd sit at `processing` forever.
        $terminalRuns = DB::table('scrape_runs')
            ->whereNotIn('status', ['running', 'paused'])
            ->whereExists(function ($query): void {
                $query->from('scrape_url_items')
                    ->whereColumn('scrape_url_items.run_id', 'scrape_runs.id')
                    ->where('scrape_url_items.status', 'processing')
                    ->whereNull('scrape_url_items.done_at');
            })
            ->pluck('id');

        $swept = 0;
        foreach ($terminalRuns as $runId) {
            $swept += RunFinisher::abortProcessingItems((int) $runId);
        }

        $swept += self::failStuckRows();

        return $swept;
    }

    /** Hung workers on runs that are still alive. */
    private static function failStuckRows(): int
    {
        $cutoff = Carbon::now('UTC')->subSeconds(self::STUCK_ROW_THRESHOLD_S);

        $items = DB::table('scrape_url_items')
            ->join('scrape_runs', 'scrape_runs.id', '=', 'scrape_url_items.run_id')
            ->whereIn('scrape_runs.status', ['running', 'paused'])
            ->where('scrape_url_items.status', 'processing')
            ->whereNull('scrape_url_items.done_at')
            ->whereNotNull('scrape_url_items.claimed_at')
            ->where('scrape_url_items.claimed_at', '<', $cutoff)
            ->get([
                'scrape_url_items.id',
                'scrape_url_items.run_id',
                'scrape_url_items.shop_id',
                'scrape_url_items.url',
                'scrape_url_items.discovered_url_id',
            ]);

        if ($items->isEmpty()) {
            return 0;
        }

        $now = Carbon::now('UTC');
        DB::table('scrape_url_items')
            ->whereIn('id', $items->pluck('id')->all())
            ->update(['status' => 'failed', 'done_at' => $now]);
        DB::table('scrape_failures')->insert($items->map(
            static fn ($item): array => [
                'scrape_url_item_id' => $item->id,
                'run_id' => $item->run_id,
                'shop_id' => $item->shop_id,
                'url' => $item->url,
                'discovered_url_id' => $item->discovered_url_id,
                'occurred_at' => $now,
                'error_reason' => 'stuck_in_processing',
                'http_status' => null,
                'error_detail' => 'stuck_in_processing',
                'lifecycle_state' => 'new',
            ]
        )->all());

        return $items->count();
    }
}
