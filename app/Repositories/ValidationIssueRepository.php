<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Support\UrlUtils;
use Illuminate\Database\ConnectionInterface;
use Illuminate\Database\DatabaseManager;
use Illuminate\Support\Facades\Date;

final readonly class ValidationIssueRepository
{
    private const array OPEN_STATES = ['new', 'acknowledged', 'snoozed'];

    public function __construct(private DatabaseManager $database) {}

    /** @param list<array<string, mixed>> $issues */
    public function upsert(array $issues, int $shopId, int $runId): void
    {
        if ($issues === []) {
            return;
        }

        $issues = $this->resolveEntityFks($issues, $shopId);

        $byShopBook = [];
        $byDiscoveredUrl = [];
        $byUrl = [];
        foreach ($issues as $issue) {
            if (($issue['shop_book_id'] ?? null) !== null) {
                $byShopBook[] = $issue;
            } elseif (($issue['discovered_url_id'] ?? null) !== null) {
                $byDiscoveredUrl[] = $issue;
            } else {
                $byUrl[] = $issue;
            }
        }

        $this->upsertBatch($byShopBook, $shopId, $runId, '(shop_book_id, field, issue) where shop_book_id is not null');
        $this->upsertBatch($byDiscoveredUrl, $shopId, $runId, '(discovered_url_id, field, issue) where discovered_url_id is not null');
        $this->upsertBatch($byUrl, $shopId, $runId, '(url, field, issue) where shop_book_id is null and discovered_url_id is null');
    }

    /**
     * @param  list<array<string, mixed>>  $issues
     * @return list<array<string, mixed>>
     */
    private function resolveEntityFks(array $issues, int $shopId): array
    {
        $urls = [];
        foreach ($issues as $issue) {
            $row = DatabaseRow::from($issue);
            $url = $row->nullableString('url');
            if ($row->nullableInt('shop_book_id') === null
                && $row->nullableInt('discovered_url_id') === null
                && $url !== null && $url !== '') {
                $urls[$url] = true;
            }
        }
        if ($urls === []) {
            return $issues;
        }
        $urls = array_keys($urls);

        $shopBookRows = $this->connection()->table('shop_books')
            ->where('shop_id', $shopId)
            ->whereIn('url', $urls)
            ->get(['id', 'url']);
        $shopBookByUrl = [];
        foreach ($shopBookRows as $raw) {
            $row = DatabaseRow::from($raw);
            $shopBookByUrl[$row->string('url')] = $row->int('id');
        }

        $leftover = array_values(array_filter(
            $urls,
            static fn (string $url): bool => ! array_key_exists($url, $shopBookByUrl)
        ));
        $discoveredByUrl = [];
        if ($leftover !== []) {

            $normalised = [];
            foreach ($leftover as $url) {
                $normalised[UrlUtils::normalize($url)] = $url;
            }
            $rows = $this->connection()->table('discovered_urls')
                ->where('shop_id', $shopId)
                ->whereIn('normalized_url', array_keys($normalised))
                ->get(['id', 'normalized_url']);
            foreach ($rows as $raw) {
                $row = DatabaseRow::from($raw);
                $url = $normalised[$row->string('normalized_url')] ?? null;
                if ($url !== null) {
                    $discoveredByUrl[$url] = $row->int('id');
                }
            }
        }

        foreach ($issues as $index => $issue) {
            $row = DatabaseRow::from($issue);
            if ($row->nullableInt('shop_book_id') !== null
                || $row->nullableInt('discovered_url_id') !== null) {
                continue;
            }
            $url = $row->nullableString('url') ?? '';
            if (isset($shopBookByUrl[$url])) {
                $issues[$index]['shop_book_id'] = $shopBookByUrl[$url];
            } elseif (isset($discoveredByUrl[$url])) {
                $issues[$index]['discovered_url_id'] = $discoveredByUrl[$url];
            }
        }

        return $issues;
    }

    /** @param list<array<string, mixed>> $batch */
    private function upsertBatch(array $batch, int $shopId, int $runId, string $conflictTarget): void
    {
        if ($batch === []) {
            return;
        }

        $now = Date::now('UTC');

        foreach (array_chunk($batch, 500) as $chunk) {
            $rows = [];
            $bindings = [];
            foreach ($chunk as $issue) {
                $issueRow = DatabaseRow::from($issue);
                $state = $issueRow->nullableString('initial_state') ?? 'new';
                $rows[] = '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)';
                $bindings[] = $shopId;
                $bindings[] = $runId;
                $bindings[] = $runId;
                $bindings[] = $issueRow->nullableString('url') ?? '';
                $bindings[] = $issueRow->nullableString('field') ?? '';
                $bindings[] = $issueRow->nullableString('issue') ?? '';
                $bindings[] = $issueRow->nullableString('raw_value');
                $bindings[] = $issueRow->nullableInt('shop_book_id');
                $bindings[] = $issueRow->nullableInt('discovered_url_id');
                $bindings[] = $state;
                $bindings[] = $state === 'acknowledged' ? $now : null;
            }

            $this->connection()->statement(
                sprintf(
                    'insert into validation_issues
                         (shop_id, last_seen_run_id, first_seen_run_id, url, field,
                          issue, raw_value, shop_book_id, discovered_url_id,
                          lifecycle_state, acknowledged_at, run_count)
                     values %s
                     on conflict %s do update set
                         last_seen_run_id = excluded.last_seen_run_id,
                         run_count = validation_issues.run_count + 1,
                         raw_value = excluded.raw_value,
                         lifecycle_state = case
                             when validation_issues.lifecycle_state = \'resolved\'
                                 then excluded.lifecycle_state
                             when validation_issues.lifecycle_state = \'snoozed\'
                                  and validation_issues.snoozed_until <= now()
                                 then \'new\'
                             else validation_issues.lifecycle_state
                         end,
                         resolved_at = case
                             when validation_issues.lifecycle_state = \'resolved\'
                                 then null
                             else validation_issues.resolved_at
                         end,
                         acknowledged_at = case
                             when validation_issues.lifecycle_state = \'resolved\'
                                  and excluded.lifecycle_state = \'acknowledged\'
                                 then excluded.acknowledged_at
                             else validation_issues.acknowledged_at
                         end',
                    implode(', ', $rows),
                    $conflictTarget
                ),
                $bindings
            );
        }
    }

    public function resolveGone(int $shopId, int $runId): int
    {
        return $this->connection()->table('validation_issues')
            ->where('shop_id', $shopId)
            ->where('last_seen_run_id', '!=', $runId)
            ->whereIn('lifecycle_state', self::OPEN_STATES)
            ->update([
                'lifecycle_state' => 'resolved',
                'resolved_at' => Date::now('UTC'),
            ]);
    }

    private function connection(): ConnectionInterface
    {
        return $this->database->connection();
    }
}
