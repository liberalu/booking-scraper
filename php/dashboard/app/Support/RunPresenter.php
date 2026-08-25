<?php

declare(strict_types=1);

namespace App\Support;

use BookScraper\Models\ScrapeRun;
use Carbon\CarbonInterface;
use Illuminate\Support\Carbon;

/**
 * Port of the run-shaping helpers in book_scraper/dashboard/routes/api.py
 * (_run_dict, _rel, _elapsed, _progress, _parse_phase).
 *
 * The React SPA is served unchanged and reads these keys directly, so the
 * output shape — including the em-dash placeholders and the constant
 * "type"/"by" fields — is a contract, not a style choice.
 */
final class RunPresenter
{
    /** @return array<string, mixed> */
    public static function toArray(
        ScrapeRun $run,
        ?int $terminalCount = null,
        int $validationIssues = 0,
        ?int $itemsAdded = null,
        ?int $itemsUpdated = null,
        bool $rescrape = false,
    ): array {
        [$phaseType, $phaseMode] = self::parsePhase($run->phase);
        if ($phaseType === 'scan' && $rescrape) {
            $phaseMode = 'full';
        }

        $added = $itemsAdded ?? $run->items_added;
        $updated = $itemsUpdated ?? $run->items_updated;

        $startedH = 0.0;
        if ($run->started_at !== null) {
            $startedH = Carbon::now('UTC')->diffInRealSeconds($run->started_at, true) / 3600;
        }

        return [
            'id' => $run->id,
            'shop' => $run->shop->name,
            'phase' => $run->phase,
            'phase_type' => $phaseType,
            'phase_mode' => $phaseMode,
            'status' => $run->status,
            'progress' => self::progress($run, $terminalCount),
            'items' => $added + $updated,
            'items_added' => $added,
            'items_updated' => $updated,
            'errors' => $run->error_count,
            'errors_4xx' => $run->errors_4xx,
            'errors_5xx' => $run->errors_5xx,
            'validation_issues' => $validationIssues,
            'elapsed' => self::elapsed($run),
            'started_ago' => self::relative($run->started_at),
            'started' => self::relative($run->started_at),
            'started_at' => self::iso($run->started_at),
            'finished_at' => self::iso($run->finished_at),
            'urls_total' => $run->urls_total,
            'urls_processed' => $run->urls_processed,
            'type' => 'full',
            'by' => '—',
            'startedH' => round($startedH, 2),
            'close_reason' => $run->close_reason,
        ];
    }

    /** 'discover_sitemap' → ['discover','sitemap']; 'scan' → ['scan','delta']. */
    public static function parsePhase(string $phase): array
    {
        if (str_starts_with($phase, 'discover_')) {
            return ['discover', substr($phase, strlen('discover_'))];
        }
        if ($phase === 'match' || $phase === 'validate') {
            return [$phase, ''];
        }

        return ['scan', 'delta'];
    }

    /**
     * `terminalCount` is done+failed scrape_url_items for the run: it counts
     * non-product fetches and 4xx/5xx as progress, because the work for
     * that URL is finished. List endpoints skip it and fall back to
     * urls_processed.
     */
    public static function progress(ScrapeRun $run, ?int $terminalCount = null): int
    {
        if ($run->status === 'completed') {
            return 100;
        }
        if ($run->urls_total === null || $run->urls_total <= 0) {
            return 0;
        }
        $processed = $terminalCount ?? $run->urls_processed;

        return min(99, (int) ($processed / $run->urls_total * 100));
    }

    public static function elapsed(ScrapeRun $run): string
    {
        $start = $run->started_at;
        if ($start === null) {
            return '—';
        }
        $end = $run->finished_at ?? Carbon::now('UTC');

        $secs = max(0, (int) $start->diffInRealSeconds($end, true));
        $s = $secs % 60;
        $m = intdiv($secs, 60) % 60;
        $h = intdiv($secs, 3600);

        if ($h > 0) {
            return $m > 0 ? "{$h}h {$m}m" : "{$h}h";
        }
        if ($m > 0) {
            return $s > 0 ? "{$m}m {$s}s" : "{$m}m";
        }

        return "{$s}s";
    }

    /** Coarse "4w ago" bucketing — matches Python's _rel exactly. */
    public static function relative(?CarbonInterface $dt): string
    {
        if ($dt === null) {
            return '—';
        }

        $s = max(0, (int) Carbon::now('UTC')->diffInRealSeconds($dt, true));
        if ($s < 60) {
            return 'just now';
        }
        $m = intdiv($s, 60);
        if ($m < 60) {
            return "{$m}m ago";
        }
        $h = intdiv($m, 60);
        if ($h < 24) {
            return "{$h}h ago";
        }
        $d = intdiv($h, 24);
        if ($d < 7) {
            return "{$d}d ago";
        }
        $w = intdiv($d, 7);
        if ($w < 5) {
            return "{$w}w ago";
        }
        $mo = intdiv($d, 30);
        if ($mo < 12) {
            return "{$mo}mo ago";
        }

        return intdiv($d, 365) . 'y ago';
    }

    /**
     * Python's datetime.isoformat(), which OMITS the microsecond component
     * when it is exactly zero ('...T02:00:00+00:00', not
     * '...T02:00:00.000000+00:00'). Cron-derived timestamps land on whole
     * seconds, so this branch fires in practice.
     */
    public static function iso(?CarbonInterface $dt): ?string
    {
        if ($dt === null) {
            return null;
        }

        $utc = $dt->utc();

        return $utc->micro === 0
            ? $utc->format('Y-m-d\TH:i:sP')
            : $utc->format('Y-m-d\TH:i:s.uP');
    }
}
