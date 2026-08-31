<?php

declare(strict_types=1);

namespace App\Repositories;

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
final class ScrapeFailureListRepository
{
    private const array LIFECYCLE_STATES = ['new', 'acknowledged', 'snoozed', 'resolved'];

    private const array SEVERITY = [
        'request_error' => 'critical',
        'anti_bot_detected' => 'critical',
        'schema_drift' => 'critical',
        'rate_limited' => 'warning',
        'robots_disallowed' => 'warning',
        'soft_404' => 'warning',
    ];

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
        string $order,
        string $sortBy,
        int $page,
        int $perPage,
    ): array {
        $query = DB::table('scrape_failures as sf')
            ->leftJoin('shop_books as sb', function (JoinClause $join): void {
                $join->on('sb.shop_id', '=', 'sf.shop_id')->on('sb.url', '=', 'sf.url');
            })
            ->leftJoin('shops as s', 's.id', '=', 'sf.shop_id');

        if (in_array($state, self::LIFECYCLE_STATES, true)) {
            $query->where('sf.lifecycle_state', $state);
        } elseif ($state === 'open') {
            $query->where('sf.lifecycle_state', '!=', 'acknowledged');
        }
        if ($shopId !== null) {
            $query->where('sf.shop_id', $shopId);
        }
        if ($runId !== null) {
            $query->where('sf.run_id', $runId);
        }
        if ($issueType !== '') {
            $query->where('sf.error_reason', $issueType);
        }
        if ($search !== '') {
            $like = "%{$search}%";
            $query->where(fn (Builder $nested): Builder => $nested->where('sf.url', 'ilike', $like)
                ->orWhere('sb.title', 'ilike', $like));
        }
        if (in_array($severity, ['critical', 'warning'], true)) {
            $this->applySeverity($query, $severity);
        }

        $total = (clone $query)->count();
        $this->order($query, $sortBy, $order);
        $rows = $query->select('sf.*', 'sb.id as sb_id', 'sb.title as sb_title', 's.name as shop_name')
            ->offset(($page - 1) * $perPage)->limit($perPage)->get();
        $issues = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $errorReason = $row->nullableString('error_reason');
            $httpStatus = $row->nullableInt('http_status');
            $issues[] = [
                'id' => $row->int('id'),
                'kind' => 'scrape_failure',
                'url' => $row->string('url'),
                'field' => 'response',
                'issue' => $errorReason ?? 'unknown',
                'raw_value' => $httpStatus === null ? null : (string) $httpStatus,
                'error_reason' => $errorReason,
                'http_status' => $httpStatus,
                'scrape_run_id' => $row->int('run_id'),
                'shop_book_id' => $row->nullableInt('sb_id'),
                'shop_book_title' => $row->nullableString('sb_title'),
                'shop_id' => $row->nullableInt('shop_id'),
                'shop_name' => $row->nullableString('shop_name'),
                'url_type' => null,
                'book_type' => null,
                'lifecycle_state' => $row->string('lifecycle_state'),
                'added_at' => $row->nullableString('occurred_at'),
                'severity' => $this->severity($errorReason, $httpStatus),
            ];
        }

        return [$issues, $total];
    }

    private function applySeverity(Builder $query, string $severity): void
    {
        $critical = array_keys(array_filter(self::SEVERITY, static fn (string $value): bool => $value === 'critical'));
        $warning = array_keys(array_filter(self::SEVERITY, static fn (string $value): bool => $value === 'warning'));
        if ($severity === 'critical') {
            $query->where(function (Builder $outer) use ($critical): void {
                $outer->where(function (Builder $nested) use ($critical): void {
                    foreach ($critical as $prefix) {
                        $nested->orWhere('sf.error_reason', 'like', "{$prefix}%");
                    }
                })->where(function (Builder $nested): void {
                    $nested->whereNull('sf.http_status')->orWhere('sf.http_status', '<', 400)->orWhere('sf.http_status', '>=', 600);
                });
            });

            return;
        }
        $query->where(function (Builder $outer) use ($warning): void {
            $outer->where(function (Builder $nested): void {
                $nested->whereNotNull('sf.http_status')->where('sf.http_status', '>=', 400)->where('sf.http_status', '<', 600);
            });
            foreach ($warning as $prefix) {
                $outer->orWhere('sf.error_reason', 'like', "{$prefix}%");
            }
        });
    }

    private function severity(?string $errorReason, ?int $httpStatus): string
    {
        if ($httpStatus !== null && $httpStatus >= 400 && $httpStatus < 600) {
            return 'warning';
        }
        if ($errorReason !== null && $errorReason !== '') {
            return self::SEVERITY[explode(':', $errorReason, 2)[0]] ?? 'warning';
        }

        return 'warning';
    }

    /** @param 'asc'|'desc' $order */
    private function order(Builder $query, string $sortBy, string $order): void
    {
        $column = match ($sortBy) {
            'id' => 'sf.id',
            'type' => 'sf.error_reason',
            'shop' => 's.name',
            'book' => 'sb.title',
            default => 'sf.occurred_at',
        };
        $query->orderBy($column, $order);
        if ($sortBy !== 'id') {
            $query->orderBy('sf.id', $order);
        }
    }
}
