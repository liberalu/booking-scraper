<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\ReadModel\ResumableRun;
use App\Runs\RunEvent;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Facades\DB;

final class ResumePolicyRepository
{
    private const int MAX_LOOKBACK = 8;

    public function chainDepth(int $runId): int
    {
        return DB::table('scrape_run_events')
            ->where('run_id', $runId)
            ->where('event_type', RunEvent::RESTARTED)
            ->count();
    }

    public function consecutiveZeroProgress(int $runId): int
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

                return DatabaseRow::from(['value' => $value])->nullableInt('value');
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

    public function findResumable(int $shopId, string $phase): ?ResumableRun
    {
        $run = $this->resumableQuery($shopId, $phase)
            ->latest('started_at')
            ->first();

        return $run === null ? null : $this->toReadModel($run);
    }

    public function findResumableById(int $runId, int $shopId, string $phase): ?ResumableRun
    {
        $run = $this->resumableQuery($shopId, $phase)
            ->where('scrape_runs.id', $runId)
            ->first();

        return $run === null ? null : $this->toReadModel($run);
    }

    private function resumableQuery(int $shopId, string $phase): Builder
    {
        return DB::table('scrape_runs')
            ->where('shop_id', $shopId)
            ->where('phase', $phase)
            ->where(function (Builder $query): void {
                $query->whereIn('status', ['running', 'paused'])
                    ->orWhere(function (Builder $inner): void {
                        $inner->where('status', 'failed')
                            ->where('resumable_after_failure', true)
                            ->where(function (Builder $reason): void {
                                $reason->whereNull('close_reason')
                                    ->orWhere('close_reason', '!=', 'heartbeat_timeout');
                            });
                    });
            })
            ->whereExists(function (Builder $query): void {
                $query->select(DB::raw(1))
                    ->from('scrape_url_items')
                    ->whereColumn('scrape_url_items.run_id', 'scrape_runs.id')
                    ->where('scrape_url_items.status', 'pending');
            });
    }

    private function toReadModel(mixed $run): ResumableRun
    {
        $row = DatabaseRow::from($run);

        return new ResumableRun(
            $row->int('id'),
            $row->int('shop_id'),
            $row->string('phase'),
            $row->string('status'),
            $row->bool('resumable_after_failure'),
        );
    }
}
