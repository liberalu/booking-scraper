<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Casts\PostgresTextArray;
use App\Support\IssueMetadata;
use Illuminate\Database\Query\Builder;
use Illuminate\Database\Query\JoinClause;
use Illuminate\Support\Facades\DB;

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
final class ValidationIssueListRepository
{
    private const array LIFECYCLE_STATES = ['new', 'acknowledged', 'snoozed', 'resolved'];

    /**
     * @param  'asc'|'desc'  $order
     * @return array{list<UnifiedIssue>, int}
     */
    public function fetch(
        string $state,
        ?int $shopId,
        string $issueType,
        ?int $runId,
        string $search,
        string $severity,
        ?string $urlType,
        ?string $bookType,
        string $order,
        string $sortBy,
        int $page,
        int $perPage,
    ): array {
        $query = DB::table('validation_issues as vi')
            ->join('scrape_runs as sr', 'sr.id', '=', 'vi.last_seen_run_id')
            ->leftJoin('shop_books as sb', 'sb.id', '=', 'vi.shop_book_id')
            ->leftJoin('discovered_urls as du', function (JoinClause $join): void {
                $join->on('du.url', '=', 'vi.url')->on('du.shop_id', '=', 'sr.shop_id');
            })
            ->leftJoin('shops as s', 's.id', '=', 'sr.shop_id');

        if (in_array($state, self::LIFECYCLE_STATES, true)) {
            $query->where('vi.lifecycle_state', $state);
        } elseif ($state === 'open') {
            $query->where('vi.lifecycle_state', 'new');
        }
        if ($shopId !== null) {
            $query->where('sr.shop_id', $shopId);
        }
        if ($issueType !== '') {
            $query->where('vi.issue', $issueType);
        }
        if (in_array($severity, ['critical', 'warning'], true)) {
            $query->whereIn('vi.issue', IssueMetadata::typesWithSeverity($severity));
        }
        if ($runId !== null) {
            $query->where('vi.last_seen_run_id', $runId);
        }
        if ($urlType !== null) {
            $query->where('du.url_type', $urlType);
        }
        if ($bookType !== null) {
            $query->where('sb.type', $bookType);
        }
        if ($search !== '') {
            $like = "%{$search}%";
            $query->where(fn (Builder $nested): Builder => $nested->where('vi.url', 'ilike', $like)
                ->orWhere('sb.title', 'ilike', $like));
        }

        $total = (clone $query)->count();
        $this->order($query, $sortBy, $order);
        $rows = $query->select(
            'vi.*',
            'sr.shop_id as run_shop_id',
            'sr.started_at as run_started_at',
            'sb.title as shop_book_title',
            'sb.type as book_type',
            'du.url_type as du_url_type',
            's.name as shop_name',
        )->offset(($page - 1) * $perPage)->limit($perPage)->get();

        $issues = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $issue = $row->string('issue');
            $issues[] = [
                'id' => $row->int('id'),
                'kind' => 'validation',
                'url' => $row->string('url'),
                'field' => $row->string('field'),
                'issue' => $issue,
                'raw_value' => $row->nullableString('raw_value'),
                'error_reason' => null,
                'http_status' => null,
                'scrape_run_id' => $row->int('last_seen_run_id'),
                'shop_book_id' => $row->nullableInt('shop_book_id'),
                'shop_book_title' => $row->nullableString('shop_book_title'),
                'shop_id' => $row->nullableInt('run_shop_id'),
                'shop_name' => $row->nullableString('shop_name'),
                'url_type' => $row->nullableString('du_url_type'),
                'book_type' => $row->nullableString('book_type'),
                'lifecycle_state' => $row->string('lifecycle_state'),
                'added_at' => $row->nullableString('run_started_at'),
                'severity' => IssueMetadata::severity($issue),
            ];
        }

        return [$issues, $total];
    }

    /** @param 'asc'|'desc' $order */
    private function order(Builder $query, string $sortBy, string $order): void
    {
        $column = match ($sortBy) {
            'id' => 'vi.id',
            'type' => 'vi.issue',
            'shop' => 's.name',
            'book' => 'sb.title',
            default => 'sr.started_at',
        };
        if ($sortBy === 'sev') {
            $query->orderByRaw(
                $order === 'asc'
                    ? 'case when vi.issue = any(?::text[]) then 1 else 2 end asc'
                    : 'case when vi.issue = any(?::text[]) then 1 else 2 end desc',
                [PostgresTextArray::encode(IssueMetadata::typesWithSeverity('critical'))],
            );
        } else {
            $query->orderBy($column, $order);
        }
        if ($sortBy !== 'id') {
            $query->orderBy('vi.id', $order);
        }
    }
}
