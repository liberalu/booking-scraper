<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Casts\PostgresTextArray;
use App\Support\IssueMetadata;
use Illuminate\Database\Query\Builder;
use Illuminate\Database\Query\JoinClause;
use Illuminate\Support\Facades\DB;
use LogicException;

/**
 * @phpstan-type UnifiedIssue array{
 *     id: int, kind: string, url: string, field: string, issue: string,
 *     raw_value: string|null, error_reason: string|null, http_status: int|null,
 *     scrape_run_id: int, shop_book_id: int|null, shop_book_title: string|null,
 *     shop_id: int|null, shop_name: string|null, url_type: string|null,
 *     book_type: string|null, lifecycle_state: string, severity: string,
 *     added_at: string|null
 * }
 */
final class UnifiedIssueReadRepository
{
    private const array LIFECYCLE_STATES = ['new', 'acknowledged', 'snoozed', 'resolved'];

    /**
     * @param  'asc'|'desc'  $order
     * @return array{rows: list<UnifiedIssue>, total: int, counts: array{new: int, acknowledged: int, snoozed: int, resolved: int, total: int}}
     */
    public function fetch(
        string $kind,
        string $state,
        ?int $shopId,
        string $issueType,
        ?int $runId,
        string $search,
        string $severity,
        ?string $urlType,
        ?string $bookType,
        string $sortBy,
        string $order,
        int $page,
        int $perPage,
    ): array {
        $union = $this->union(
            $kind,
            $state,
            $shopId,
            $issueType,
            $runId,
            $search,
            $severity,
            $urlType,
            $bookType,
        );
        $query = DB::query()->fromSub($union, 'issues');
        $total = (clone $query)->count();
        $column = match ($sortBy) {
            'id' => 'id',
            'type' => 'issue',
            'shop' => 'shop_name',
            'book' => 'shop_book_title',
            'sev' => 'severity_rank',
            default => 'added_at',
        };
        $rows = $query->orderBy($column, $order)
            ->orderBy('id', $order)
            ->orderByRaw("case when kind = 'validation' then 0 else 1 end")
            ->offset(($page - 1) * $perPage)
            ->limit($perPage)
            ->get();

        $issues = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $issues[] = [
                'id' => $row->int('id'),
                'kind' => $row->string('kind'),
                'url' => $row->string('url'),
                'field' => $row->string('field'),
                'issue' => $row->string('issue'),
                'raw_value' => $row->nullableString('raw_value'),
                'error_reason' => $row->nullableString('error_reason'),
                'http_status' => $row->nullableInt('http_status'),
                'scrape_run_id' => $row->int('scrape_run_id'),
                'shop_book_id' => $row->nullableInt('shop_book_id'),
                'shop_book_title' => $row->nullableString('shop_book_title'),
                'shop_id' => $row->nullableInt('shop_id'),
                'shop_name' => $row->nullableString('shop_name'),
                'url_type' => $row->nullableString('url_type'),
                'book_type' => $row->nullableString('book_type'),
                'lifecycle_state' => $row->string('lifecycle_state'),
                'severity' => $row->string('kind') === 'validation'
                    ? IssueMetadata::severity($row->string('issue'))
                    : ($row->int('severity_rank') === 1 ? 'critical' : 'warning'),
                'added_at' => $row->nullableString('added_at'),
            ];
        }

        $countsUnion = $this->union(
            $kind,
            '',
            $shopId,
            $issueType,
            $runId,
            $search,
            $severity,
            $urlType,
            $bookType,
        );

        return ['rows' => $issues, 'total' => $total, 'counts' => $this->counts($countsUnion)];
    }

    private function union(
        string $kind,
        string $state,
        ?int $shopId,
        string $issueType,
        ?int $runId,
        string $search,
        string $severity,
        ?string $urlType,
        ?string $bookType,
    ): Builder {
        $queries = [];
        if ($kind !== 'scrape_failure') {
            $queries[] = $this->validationQuery(
                $state, $shopId, $issueType, $runId, $search, $severity, $urlType, $bookType,
            );
        }
        if ($kind !== 'validation') {
            $queries[] = $this->failureQuery($state, $shopId, $issueType, $runId, $search, $severity);
        }

        $union = array_shift($queries) ?? throw new LogicException('At least one issue source is required');
        foreach ($queries as $query) {
            $union->unionAll($query);
        }

        return $union;
    }

    private function validationQuery(
        string $state,
        ?int $shopId,
        string $issueType,
        ?int $runId,
        string $search,
        string $severity,
        ?string $urlType,
        ?string $bookType,
    ): Builder {
        $critical = IssueMetadata::typesWithSeverity('critical');
        $query = DB::table('validation_issues as vi')
            ->join('scrape_runs as sr', 'sr.id', '=', 'vi.last_seen_run_id')
            ->leftJoin('shop_books as sb', 'sb.id', '=', 'vi.shop_book_id')
            ->leftJoin('discovered_urls as du', function (JoinClause $join): void {
                $join->on('du.url', '=', 'vi.url')->on('du.shop_id', '=', 'sr.shop_id');
            })
            ->leftJoin('shops as s', 's.id', '=', 'sr.shop_id')
            ->selectRaw("vi.id, 'validation'::text as kind, vi.url, vi.field, vi.issue,
                vi.raw_value::text as raw_value, null::text as error_reason, null::int as http_status,
                vi.last_seen_run_id as scrape_run_id, vi.shop_book_id, sb.title as shop_book_title,
                sr.shop_id, s.name as shop_name, du.url_type::text as url_type,
                sb.type::text as book_type, vi.lifecycle_state::text as lifecycle_state,
                sr.started_at as added_at,
                case when vi.issue = any(?::text[]) then 1 else 2 end as severity_rank",
                [PostgresTextArray::encode($critical)],
            );
        $this->applyState($query, 'vi.lifecycle_state', $state, false);
        $this->commonFilters($query, 'sr.shop_id', 'vi.last_seen_run_id', 'vi.issue', $shopId, $runId, $issueType);
        if ($severity !== '') {
            $query->whereIn('vi.issue', IssueMetadata::typesWithSeverity($severity));
        }
        if ($urlType !== null) {
            $query->where('du.url_type', $urlType);
        }
        if ($bookType !== null) {
            $query->where('sb.type', $bookType);
        }
        $this->applySearch($query, 'vi.url', $search);

        return $query;
    }

    private function failureQuery(
        string $state,
        ?int $shopId,
        string $issueType,
        ?int $runId,
        string $search,
        string $severity,
    ): Builder {
        $critical = ['request_error', 'anti_bot_detected', 'schema_drift'];
        $query = DB::table('scrape_failures as sf')
            ->leftJoin('shop_books as sb', function (JoinClause $join): void {
                $join->on('sb.shop_id', '=', 'sf.shop_id')->on('sb.url', '=', 'sf.url');
            })
            ->leftJoin('shops as s', 's.id', '=', 'sf.shop_id')
            ->selectRaw("sf.id, 'scrape_failure'::text as kind, sf.url, 'response'::text as field,
                coalesce(sf.error_reason, 'unknown') as issue, sf.http_status::text as raw_value,
                sf.error_reason, sf.http_status, sf.run_id as scrape_run_id,
                sb.id as shop_book_id, sb.title as shop_book_title, sf.shop_id, s.name as shop_name,
                null::text as url_type, null::text as book_type,
                sf.lifecycle_state::text as lifecycle_state,
                sf.occurred_at as added_at,
                case when (sf.http_status is null or sf.http_status < 400 or sf.http_status >= 600)
                    and (sf.error_reason like 'request_error%' or sf.error_reason like 'anti_bot_detected%'
                        or sf.error_reason like 'schema_drift%') then 1 else 2 end as severity_rank");
        $this->applyState($query, 'sf.lifecycle_state', $state, true);
        $this->commonFilters($query, 'sf.shop_id', 'sf.run_id', 'sf.error_reason', $shopId, $runId, $issueType);
        $this->applySearch($query, 'sf.url', $search);
        if ($severity === 'critical') {
            $query->where(function (Builder $outer) use ($critical): void {
                $outer->where(function (Builder $reasons) use ($critical): void {
                    foreach ($critical as $prefix) {
                        $reasons->orWhere('sf.error_reason', 'like', "{$prefix}%");
                    }
                })->where(fn (Builder $status): Builder => $status->whereNull('sf.http_status')
                    ->orWhere('sf.http_status', '<', 400)->orWhere('sf.http_status', '>=', 600));
            });
        } elseif ($severity === 'warning') {
            $query->whereNot(function (Builder $outer) use ($critical): void {
                $outer->where(function (Builder $reasons) use ($critical): void {
                    foreach ($critical as $prefix) {
                        $reasons->orWhere('sf.error_reason', 'like', "{$prefix}%");
                    }
                })->where(fn (Builder $status): Builder => $status->whereNull('sf.http_status')
                    ->orWhere('sf.http_status', '<', 400)->orWhere('sf.http_status', '>=', 600));
            });
        } elseif ($severity === 'info') {
            $query->whereRaw('false');
        }

        return $query;
    }

    private function applyState(Builder $query, string $column, string $state, bool $failure): void
    {
        if (in_array($state, self::LIFECYCLE_STATES, true)) {
            $query->where($column, $state);
        } elseif ($state === 'open') {
            $failure ? $query->where($column, '!=', 'acknowledged') : $query->where($column, 'new');
        }
    }

    private function commonFilters(
        Builder $query,
        string $shopColumn,
        string $runColumn,
        string $issueColumn,
        ?int $shopId,
        ?int $runId,
        string $issueType,
    ): void {
        $query->when($shopId !== null, fn (Builder $builder): Builder => $builder->where($shopColumn, $shopId))
            ->when($runId !== null, fn (Builder $builder): Builder => $builder->where($runColumn, $runId))
            ->when($issueType !== '', fn (Builder $builder): Builder => $builder->where($issueColumn, $issueType));
    }

    private function applySearch(Builder $query, string $urlColumn, string $search): void
    {
        if ($search === '') {
            return;
        }
        $like = "%{$search}%";
        $query->where(fn (Builder $nested): Builder => $nested->where($urlColumn, 'ilike', $like)
            ->orWhere('sb.title', 'ilike', $like));
    }

    /** @return array{new: int, acknowledged: int, snoozed: int, resolved: int, total: int} */
    private function counts(Builder $union): array
    {
        $counts = [];
        foreach (DB::query()->fromSub($union, 'issues')->select('lifecycle_state')
            ->selectRaw('count(*) as count')->groupBy('lifecycle_state')->get() as $raw) {
            $row = DatabaseRow::from($raw);
            $counts[$row->string('lifecycle_state')] = $row->int('count');
        }

        return [
            'new' => $counts['new'] ?? 0,
            'acknowledged' => $counts['acknowledged'] ?? 0,
            'snoozed' => $counts['snoozed'] ?? 0,
            'resolved' => $counts['resolved'] ?? 0,
            'total' => array_sum($counts),
        ];
    }
}
