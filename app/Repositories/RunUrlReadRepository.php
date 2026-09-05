<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\Request\RunQueryInput;
use App\Models\ScrapeRun;
use App\Support\Queries;
use Carbon\CarbonImmutable;
use Illuminate\Database\Query\JoinClause;
use Illuminate\Support\Facades\DB;

final class RunUrlReadRepository
{
    private const array STATUSES = ['pending', 'processing', 'done', 'failed'];

    private const array SORT_KEYS = [
        'id', 'started', 'done', 'duration', 'status', 'http', 'url_type', 'url', 'title',
    ];

    private const array PHASE_TO_SOURCE = [
        'discover_sitemap' => 'sitemap',
        'discover_categories' => 'category',
        'discover_full_crawl' => 'full_crawl',
    ];

    /** @return array<string, mixed> */
    public function __invoke(RunQueryInput $input, ScrapeRun $run): array
    {
        $runId = $run->id;

        $status = $input->status ?? 'all';
        $page = max(1, $input->page ?? 1);
        $perPage = max(1, min($input->perPage ?? 50, 200));
        $sort = $input->sort ?? 'started';
        $order = $input->order === 'asc' ? 'asc' : 'desc';

        $breakdown = $this->breakdown($runId);
        $hasLive = array_sum($breakdown) > 0;

        if ($hasLive) {
            if (! in_array($status, ['all', ...self::STATUSES], true)) {
                $status = 'all';
            }
            [$rows, $total] = $this->liveRows($input, $runId, $status, $sort, $order, $page, $perPage);
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
    private function breakdown(int $runId): array
    {
        $counts = array_fill_keys(self::STATUSES, 0);
        foreach (DB::table('scrape_url_items')
            ->select('status')
            ->selectRaw('count(id) as c')
            ->where('run_id', $runId)
            ->groupBy('status')
            ->get() as $result) {
            $row = DatabaseRow::from($result);
            $counts[$row->string('status')] = $row->int('c');
        }

        return $counts;
    }

    /** @return array{list<array<string, mixed>>, int} */
    private function liveRows(
        RunQueryInput $input,
        int $runId,
        string $status,
        string $sort,
        string $order,
        int $page,
        int $perPage,
    ): array {
        $errorReason = $input->errorReason;
        $errorReasonIsNull = $input->errorReasonIsNull;
        $httpStatus = $input->httpStatus;
        $httpStatusIsNull = $input->httpStatusIsNull;

        $needsFailureFilter = $errorReasonIsNull || $errorReason !== ''
            || $httpStatusIsNull || $httpStatus !== null;

        $latest = DB::table('scrape_failures')
            ->select('scrape_url_item_id', 'error_reason', 'http_status')
            ->selectRaw(
                'row_number() over (partition by scrape_url_item_id '
                .'order by occurred_at desc, id desc) as rn'
            )
            ->where('run_id', $runId);

        $query = DB::table('scrape_url_items as sui')

            ->leftJoin('shop_books as sb', function (JoinClause $join): void {
                $join->on('sb.shop_id', '=', 'sui.shop_id')->on('sb.url', '=', 'sui.url');
            })
            ->where('sui.run_id', $runId);

        if (in_array($status, self::STATUSES, true)) {
            $query->where('sui.status', $status);
        }

        if ($needsFailureFilter) {
            $query->joinSub($latest, 'lf', function (JoinClause $join): void {
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
            $query->leftJoinSub($latest, 'lf', function (JoinClause $join): void {
                $join->on('lf.scrape_url_item_id', '=', 'sui.id')->where('lf.rn', 1);
            });
        }

        $total = (clone $query)->count();

        if (! in_array($sort, self::SORT_KEYS, true)) {
            $sort = 'started';
        }
        $rows = $query
            ->select('sui.*', 'sb.title as sb_title', 'sb.id as sb_id', 'lf.error_reason as latest_error_reason')
            ->orderByRaw($this->orderExpression($sort, $order))
            ->orderBy('sui.id')
            ->offset(($page - 1) * $perPage)
            ->limit($perPage)
            ->get();

        return [
            array_values($rows->map(function (mixed $result): array {
                $row = DatabaseRow::from($result);
                $claimed = $row->value('claimed_at') !== null ? $row->dateTime('claimed_at') : null;
                $done = $row->value('done_at') !== null ? $row->dateTime('done_at') : null;

                return [
                    'url' => $row->string('url'),
                    'title' => $row->nullableString('sb_title'),
                    'status' => $row->string('status'),
                    'url_type' => $row->nullableString('url_type'),
                    'claimed_at' => $this->iso($claimed),
                    'done_at' => $this->iso($done),
                    'http_status' => $row->nullableInt('http_status'),

                    'error_reason' => $row->string('status') === 'failed'
                        ? $row->nullableString('latest_error_reason')
                        : null,
                    'duration_ms' => ($claimed instanceof CarbonImmutable && $done instanceof CarbonImmutable)
                        ? (int) ($claimed->diffInSeconds($done, true) * 1000)
                        : null,
                    'request_delay_s' => $row->nullableFloat('request_delay_s'),
                    'delay_source' => $row->nullableString('delay_source'),
                    'response_bytes' => $row->nullableInt('response_bytes'),
                    'item_id' => $row->int('id'),
                    'discovered_url_id' => $row->nullableInt('discovered_url_id'),
                    'shop_book_id' => $row->nullableInt('sb_id'),
                    'attempts' => $row->int('attempts'),
                ];
            })->all()),
            $total,
        ];
    }

    /** @return array{list<array<string, mixed>>, int} */
    private function historyRows(ScrapeRun $run, int $page, int $perPage): array
    {
        if (! str_starts_with($run->phase, 'discover')) {
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
            array_values($rows->map(function (mixed $result): array {
                $row = DatabaseRow::from($result);

                return [
                    'id' => $row->int('id'),
                    'url' => $row->string('url'),
                    'url_type' => $row->nullableString('url_type'),
                    'last_http_status' => $row->nullableInt('last_http_status'),
                    'last_checked_at' => $this->iso(
                        $row->value('last_checked_at') !== null ? $row->dateTime('last_checked_at') : null,
                    ),
                ];
            })->all()),
            $total,
        ];
    }

    private function iso(?CarbonImmutable $dt): ?string
    {
        if (! $dt instanceof CarbonImmutable) {
            return null;
        }
        $utc = $dt->utc();

        return $utc->micro === 0
            ? $utc->format('Y-m-d\TH:i:sP')
            : $utc->format('Y-m-d\TH:i:s.uP');
    }

    /** @return literal-string */
    private function orderExpression(string $sort, string $order): string
    {
        if ($order === 'asc') {
            return match ($sort) {
                'id' => 'sui.id asc nulls last',
                'started' => 'sui.claimed_at asc nulls last',
                'done' => 'sui.done_at asc nulls last',
                'duration' => 'sui.done_at - sui.claimed_at asc nulls last',
                'status' => "case sui.status when 'processing' then 0 when 'pending' then 1 when 'failed' then 2 when 'done' then 3 else 4 end asc nulls last",
                'http' => 'sui.http_status asc nulls last',
                'url_type' => 'sui.url_type asc nulls last',
                'title' => 'sb.title asc nulls last',
                default => 'sui.url asc nulls last',
            };
        }

        return match ($sort) {
            'id' => 'sui.id desc nulls last',
            'started' => 'sui.claimed_at desc nulls last',
            'done' => 'sui.done_at desc nulls last',
            'duration' => 'sui.done_at - sui.claimed_at desc nulls last',
            'status' => "case sui.status when 'processing' then 0 when 'pending' then 1 when 'failed' then 2 when 'done' then 3 else 4 end desc nulls last",
            'http' => 'sui.http_status desc nulls last',
            'url_type' => 'sui.url_type desc nulls last',
            'title' => 'sb.title desc nulls last',
            default => 'sui.url desc nulls last',
        };
    }
}
