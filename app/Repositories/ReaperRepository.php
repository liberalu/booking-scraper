<?php

declare(strict_types=1);

namespace App\Repositories;

use Illuminate\Database\Query\Builder;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

final class ReaperRepository
{
    public const DEAD_RUN_SECONDS = 60;

    public const STUCK_ROW_THRESHOLD_S = 120;

    public const PAUSED_RUN_SECONDS = 604800;

    public const RESUMABLE_RETENTION_SECONDS = 604800;

    public function __construct(
        private readonly RunFinisherRepository $finisher = new RunFinisherRepository,
    ) {}

    /** @return list<array{run_id: int, shop: string, phase: string, close_reason: string}> */
    public function sweep(): array
    {
        $now = Carbon::now('UTC');

        $candidates = DB::table('scrape_runs')
            ->join('shops', 'shops.id', '=', 'scrape_runs.shop_id')
            ->whereIn('scrape_runs.status', ['running', 'stopping', 'paused'])
            ->get([
                'scrape_runs.id',
                'scrape_runs.status',
                'scrape_runs.last_heartbeat',
                'scrape_runs.started_at',
                'scrape_runs.phase',
                'shops.name as shop',
            ]);

        $killed = [];
        foreach ($candidates as $raw) {
            $run = DatabaseRow::from($raw);
            $lastActivity = $run->nullableString('last_heartbeat') ?? $run->nullableString('started_at');
            $status = $run->string('status');
            $timeout = $status === 'paused'
                ? self::PAUSED_RUN_SECONDS
                : self::DEAD_RUN_SECONDS;
            if ($lastActivity === null
                || Carbon::parse($lastActivity)->gte($now->copy()->subSeconds($timeout))) {
                continue;
            }

            $reason = match ($status) {
                'paused' => 'paused_timeout',
                'stopping' => 'stop_timeout',
                default => 'heartbeat_timeout',
            };

            $this->finisher->finish($run->int('id'), 'failed', $reason);
            $killed[] = [
                'run_id' => $run->int('id'),
                'shop' => $run->string('shop'),
                'phase' => $run->string('phase'),
                'close_reason' => $reason,
            ];
        }

        $this->sweepOrphanedProcessingItems();
        $this->expireResumableFailures();

        return $killed;
    }

    public function expireResumableFailures(): int
    {
        return DB::table('scrape_runs')
            ->where('status', 'failed')
            ->where('resumable_after_failure', true)
            ->where('finished_at', '<', Carbon::now('UTC')->subSeconds(
                self::RESUMABLE_RETENTION_SECONDS,
            ))
            ->update(['resumable_after_failure' => false]);
    }

    public function sweepOrphanedProcessingItems(): int
    {

        $terminalRuns = DB::table('scrape_runs')
            ->whereNotIn('status', ['running', 'paused'])
            ->whereExists(function (Builder $query): void {
                $query->from('scrape_url_items')
                    ->whereColumn('scrape_url_items.run_id', 'scrape_runs.id')
                    ->where('scrape_url_items.status', 'processing')
                    ->whereNull('scrape_url_items.done_at');
            })
            ->pluck('id');

        $swept = 0;
        foreach ($terminalRuns as $runId) {
            $swept += $this->finisher->abortProcessingItems(
                DatabaseRow::from(['id' => $runId])->int('id'),
            );
        }

        $swept += $this->failStuckRows();

        return $swept;
    }

    private function failStuckRows(): int
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
