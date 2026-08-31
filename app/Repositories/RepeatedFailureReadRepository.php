<?php

declare(strict_types=1);

namespace App\Repositories;

use Illuminate\Support\Facades\DB;

final class RepeatedFailureReadRepository
{
    private const int THRESHOLD = 3;

    private const array TERMINAL = ['completed', 'failed'];

    /** @return array<string, mixed> */
    public function __invoke(): array
    {

        $pairs = DB::table('scrape_runs')
            ->select('shop_id', 'phase')
            ->whereIn('status', self::TERMINAL)
            ->groupBy('shop_id', 'phase')
            ->get();

        $items = [];
        foreach ($pairs as $pairRaw) {
            $pair = DatabaseRow::from($pairRaw);
            $recentRows = DB::table('scrape_runs')
                ->join('shops', 'shops.id', '=', 'scrape_runs.shop_id')
                ->where('scrape_runs.shop_id', $pair->int('shop_id'))
                ->where('scrape_runs.phase', $pair->string('phase'))
                ->whereIn('status', self::TERMINAL)
                ->orderByRaw('finished_at desc nulls last')
                ->limit(self::THRESHOLD)
                ->get(['scrape_runs.id', 'scrape_runs.status', 'shops.name as shop_name']);

            if ($recentRows->count() < self::THRESHOLD) {
                continue;
            }
            $recent = [];
            $hasNonFailure = false;
            foreach ($recentRows as $raw) {
                $row = DatabaseRow::from($raw);
                $recent[] = $row;
                $hasNonFailure = $hasNonFailure || $row->string('status') !== 'failed';
            }
            if ($hasNonFailure) {
                continue;
            }

            $runIds = array_map(static fn (DatabaseRow $row): int => $row->int('id'), $recent);
            $reasons = $this->failureReasons($runIds);
            $observed = array_values(array_unique(array_filter(
                array_map(static fn (DatabaseRow $row): ?string => $reasons[$row->int('id')] ?? null, $recent),
                static fn (?string $v): bool => $v !== null
            )));

            if (count($observed) !== 1) {
                continue;
            }

            $items[] = [
                'shop' => $recent[0]->nullableString('shop_name') ?? '?',
                'phase' => $pair->string('phase'),
                'count' => self::THRESHOLD,
                'error_reason' => $observed[0],
                'latest_run_id' => $recent[0]->int('id'),
            ];
        }

        return ['items' => $items];
    }

    /**
     * @param  list<int>  $runIds
     * @return array<int, string>
     */
    private function failureReasons(array $runIds): array
    {
        if ($runIds === []) {
            return [];
        }

        $rows = DB::table('validation_issues')
            ->select('last_seen_run_id', 'raw_value')
            ->whereIn('last_seen_run_id', $runIds)
            ->where('issue', 'scrape_run_failed')
            ->get();
        $reasons = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $reason = $row->nullableString('raw_value');
            if ($reason !== null) {
                $reasons[$row->int('last_seen_run_id')] = $reason;
            }
        }

        return $reasons;
    }
}
