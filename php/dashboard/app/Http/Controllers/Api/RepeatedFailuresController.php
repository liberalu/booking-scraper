<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use BookScraper\Models\ScrapeRun;
use Illuminate\Support\Facades\DB;

/**
 * GET /api/runs/repeated-failures — banner data for the run list.
 *
 * Fires when the last N terminal runs of a (shop, phase) all failed with
 * the SAME recorded error_reason. Differing reasons read as transient and
 * deliberately do not alert; any success in the window resets the streak.
 */
final class RepeatedFailuresController
{
    /** Consecutive same-reason failures needed to alert. */
    private const THRESHOLD = 3;

    private const TERMINAL = ['completed', 'failed'];

    public function __invoke(): array
    {
        // Volume is tiny (a few shops × a few phases), so the streak check
        // runs per pair rather than as one clever window query.
        $pairs = ScrapeRun::query()
            ->select('shop_id', 'phase')
            ->whereIn('status', self::TERMINAL)
            ->groupBy('shop_id', 'phase')
            ->get();

        $items = [];
        foreach ($pairs as $pair) {
            $recent = ScrapeRun::with('shop')
                ->where('shop_id', $pair->shop_id)
                ->where('phase', $pair->phase)
                ->whereIn('status', self::TERMINAL)
                ->orderByRaw('finished_at desc nulls last')
                ->limit(self::THRESHOLD)
                ->get();

            if ($recent->count() < self::THRESHOLD) {
                continue;
            }
            if ($recent->contains(fn (ScrapeRun $r): bool => $r->status !== 'failed')) {
                continue;
            }

            $reasons = self::failureReasons($recent->pluck('id')->all());
            $observed = array_values(array_unique(array_filter(
                $recent->map(fn (ScrapeRun $r): ?string => $reasons[$r->id] ?? null)->all(),
                static fn (?string $v): bool => $v !== null
            )));

            // Exactly one shared reason, or it's transient.
            if (count($observed) !== 1) {
                continue;
            }

            $items[] = [
                'shop' => $recent->first()->shop->name ?? '?',
                'phase' => $pair->phase,
                'count' => self::THRESHOLD,
                'error_reason' => $observed[0],
                'latest_run_id' => $recent->first()->id,
            ];
        }

        return ['items' => $items];
    }

    /**
     * record_scrape_run_failed_issue() writes one validation_issues row per
     * failed run, carrying the reason in raw_value.
     *
     * @return array<int, string|null>
     */
    private static function failureReasons(array $runIds): array
    {
        if ($runIds === []) {
            return [];
        }

        return DB::table('validation_issues')
            ->select('last_seen_run_id', 'raw_value')
            ->whereIn('last_seen_run_id', $runIds)
            ->where('issue', 'scrape_run_failed')
            ->pluck('raw_value', 'last_seen_run_id')
            ->all();
    }
}
