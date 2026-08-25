<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\Queries;
use BookScraper\Models\ScrapeRun;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * GET /api/runs/{id}/urls — the run's URL queue.
 *
 * Reads `scrape_url_items` when the run has any (all runs since those rows
 * started being kept after completion). Old discover runs predate that, so
 * they fall back to `discovered_urls` via last_seen_run_id.
 */
final class RunUrlsController
{
    private const STATUSES = ['pending', 'processing', 'done', 'failed'];

    private const SORT_KEYS = [
        'id', 'started', 'done', 'duration', 'status', 'http', 'url_type', 'url', 'title',
    ];

    /** discover phase -> the discovered_urls.source it wrote. */
    private const PHASE_TO_SOURCE = [
        'discover_sitemap' => 'sitemap',
        'discover_categories' => 'category',
        'discover_full_crawl' => 'full_crawl',
    ];

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function __invoke(Request $request, int $runId): mixed
    {
        $run = ScrapeRun::find($runId);
        if ($run === null) {
            return response()->json(['detail' => 'Run not found'], 404);
        }

        $status = (string) $request->query('status', 'all');
        $page = max(1, (int) $request->query('page', 1));
        $perPage = max(1, min((int) $request->query('per_page', 50), 200));
        $sort = (string) $request->query('sort', 'started');
        $order = $request->query('order') === 'asc' ? 'asc' : 'desc';

        $breakdown = self::breakdown($runId);
        $hasLive = array_sum($breakdown) > 0;

        if ($hasLive) {
            if (!in_array($status, ['all', ...self::STATUSES], true)) {
                $status = 'all';
            }
            [$rows, $total] = $this->liveRows($request, $runId, $status, $sort, $order, $page, $perPage);
            $source = 'live';
        } else {
            [$rows, $total] = $this->historyRows($run, $page, $perPage);
            $source = 'history';
            $status = 'all';
        }

        return [
            'source' => $source,
            'breakdown' => $breakdown,
            'status' => $status,
            'statuses' => self::STATUSES,
            'sort' => $sort,
            'order' => $order,
            'rows' => $rows,
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'pages' => Queries::pageCount($total, $perPage),
        ];
    }

    /** @return array<string, int> */
    private static function breakdown(int $runId): array
    {
        $counts = array_fill_keys(self::STATUSES, 0);
        foreach (DB::table('scrape_url_items')
            ->select('status')
            ->selectRaw('count(id) as c')
            ->where('run_id', $runId)
            ->groupBy('status')
            ->get() as $row) {
            $counts[$row->status] = (int) $row->c;
        }

        return $counts;
    }

    /** @return array{0: list<array<string, mixed>>, 1: int} */
    private function liveRows(
        Request $request,
        int $runId,
        string $status,
        string $sort,
        string $order,
        int $page,
        int $perPage,
    ): array {
        $errorReason = (string) $request->query('error_reason', '');
        $errorReasonIsNull = $request->boolean('error_reason_is_null');
        $httpStatus = $request->query('http_status');
        $httpStatus = ($httpStatus === null || $httpStatus === '') ? null : (int) $httpStatus;
        $httpStatusIsNull = $request->boolean('http_status_is_null');

        $needsFailureFilter = $errorReasonIsNull || $errorReason !== ''
            || $httpStatusIsNull || $httpStatus !== null;

        // The latest failure event per item. Always joined so the row builder
        // can show the reason without a second query; INNER when filtering so
        // items with no failure history drop out.
        $latest = DB::table('scrape_failures')
            ->select('scrape_url_item_id', 'error_reason', 'http_status')
            ->selectRaw(
                'row_number() over (partition by scrape_url_item_id '
                . 'order by occurred_at desc, id desc) as rn'
            )
            ->where('run_id', $runId);

        $query = DB::table('scrape_url_items as sui')
            // Matched on (shop_id, url): the queue row has no FK to the book.
            ->leftJoin('shop_books as sb', function ($join): void {
                $join->on('sb.shop_id', '=', 'sui.shop_id')->on('sb.url', '=', 'sui.url');
            })
            ->where('sui.run_id', $runId);

        if (in_array($status, self::STATUSES, true)) {
            $query->where('sui.status', $status);
        }

        if ($needsFailureFilter) {
            $query->joinSub($latest, 'lf', function ($join): void {
                $join->on('lf.scrape_url_item_id', '=', 'sui.id')->where('lf.rn', 1);
            });
            if ($errorReasonIsNull) {
                $query->whereNull('lf.error_reason');
            } elseif ($errorReason !== '') {
                $query->where('lf.error_reason', $errorReason);
            }
            if ($httpStatusIsNull) {
                $query->whereNull('lf.http_status');
            } elseif ($httpStatus !== null) {
                $query->where('lf.http_status', $httpStatus);
            }
        } else {
            $query->leftJoinSub($latest, 'lf', function ($join): void {
                $join->on('lf.scrape_url_item_id', '=', 'sui.id')->where('lf.rn', 1);
            });
        }

        $total = (clone $query)->count();

        if (!in_array($sort, self::SORT_KEYS, true)) {
            $sort = 'started';
        }
        $expression = match ($sort) {
            'id' => 'sui.id',
            'started' => 'sui.claimed_at',
            'done' => 'sui.done_at',
            'duration' => 'sui.done_at - sui.claimed_at',
            // Operationally meaningful order, not alphabetical.
            'status' => "case sui.status when 'processing' then 0 when 'pending' then 1"
                . " when 'failed' then 2 when 'done' then 3 else 4 end",
            'http' => 'sui.http_status',
            'url_type' => 'sui.url_type',
            'title' => 'sb.title',
            default => 'sui.url',
        };

        $rows = $query
            ->select('sui.*', 'sb.title as sb_title', 'sb.id as sb_id', 'lf.error_reason as latest_error_reason')
            ->orderByRaw("{$expression} {$order} nulls last")
            ->orderBy('sui.id')
            ->offset(($page - 1) * $perPage)
            ->limit($perPage)
            ->get();

        return [
            $rows->map(function (object $row): array {
                $claimed = $row->claimed_at !== null ? Carbon::parse($row->claimed_at) : null;
                $done = $row->done_at !== null ? Carbon::parse($row->done_at) : null;

                return [
                    'url' => $row->url,
                    'title' => $row->sb_title,
                    'status' => $row->status,
                    'url_type' => $row->url_type,
                    'claimed_at' => self::iso($claimed),
                    'done_at' => self::iso($done),
                    'http_status' => $row->http_status,
                    // Only on a currently-failed row: a URL that was retried
                    // and succeeded must not still show its old failure.
                    'error_reason' => $row->status === 'failed' ? $row->latest_error_reason : null,
                    'duration_ms' => ($claimed !== null && $done !== null)
                        ? (int) ($claimed->diffInRealSeconds($done, true) * 1000)
                        : null,
                    'request_delay_s' => $row->request_delay_s !== null ? (float) $row->request_delay_s : null,
                    'delay_source' => $row->delay_source,
                    'response_bytes' => $row->response_bytes,
                    'item_id' => (int) $row->id,
                    'discovered_url_id' => $row->discovered_url_id,
                    'shop_book_id' => $row->sb_id !== null ? (int) $row->sb_id : null,
                    'attempts' => (int) $row->attempts,
                ];
            })->all(),
            $total,
        ];
    }

    /**
     * Fallback for discover runs that finished before queue rows were kept.
     *
     * @return array{0: list<array<string, mixed>>, 1: int}
     */
    private function historyRows(ScrapeRun $run, int $page, int $perPage): array
    {
        if (!str_starts_with($run->phase, 'discover')) {
            return [[], 0];
        }

        $query = DB::table('discovered_urls')->where('last_seen_run_id', $run->id);
        $source = self::PHASE_TO_SOURCE[$run->phase] ?? null;
        if ($source !== null) {
            $query->where('source', $source);
        }

        $total = (clone $query)->count();
        $rows = $query
            ->orderByRaw('last_checked_at desc nulls last')
            ->orderByDesc('id')
            ->offset(($page - 1) * $perPage)
            ->limit($perPage)
            ->get();

        return [
            $rows->map(fn (object $r): array => [
                'id' => (int) $r->id,
                'url' => $r->url,
                'url_type' => $r->url_type,
                'last_http_status' => $r->last_http_status,
                'last_checked_at' => self::iso(
                    $r->last_checked_at !== null ? Carbon::parse($r->last_checked_at) : null
                ),
            ])->all(),
            $total,
        ];
    }

    private static function iso(?Carbon $dt): ?string
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
