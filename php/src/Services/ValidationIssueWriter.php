<?php

declare(strict_types=1);

namespace BookScraper\Services;

use BookScraper\UrlUtils;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * Persists validator findings, ported from upsert_validation_issues() and
 * resolve_gone_issues() in book_scraper/db/repo.py.
 *
 * One canonical row per entity × field × issue type, enforced by three
 * PARTIAL unique indexes (shop_book / discovered_url / bare url), so each
 * batch needs its own ON CONFLICT target — hence the three-way split below.
 */
final class ValidationIssueWriter
{
    /** Lifecycle states that count as still-open. */
    private const OPEN_STATES = ['new', 'acknowledged', 'snoozed'];

    /**
     * @param list<array<string, mixed>> $issues
     */
    public function upsert(array $issues, int $shopId, int $runId): void
    {
        if ($issues === []) {
            return;
        }

        $issues = $this->resolveEntityFks($issues, $shopId);

        // Split by which partial index applies.
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
     * Point each issue at the shop_book or discovered_url its URL names.
     *
     * The validator supplies these itself — it works from stored rows — but an
     * issue noticed mid-crawl has only a URL. Without the FK it lands in the
     * url-keyed partial index instead of the entity-keyed one, so the same
     * problem on the same book would open a second row and never resolve.
     *
     * @param  list<array<string, mixed>>  $issues
     * @return list<array<string, mixed>>
     */
    private function resolveEntityFks(array $issues, int $shopId): array
    {
        $urls = [];
        foreach ($issues as $issue) {
            if (($issue['shop_book_id'] ?? null) === null
                && ($issue['discovered_url_id'] ?? null) === null
                && ($issue['url'] ?? '') !== '') {
                $urls[(string) $issue['url']] = true;
            }
        }
        if ($urls === []) {
            return $issues;
        }
        $urls = array_keys($urls);

        $shopBookByUrl = DB::table('shop_books')
            ->where('shop_id', $shopId)
            ->whereIn('url', $urls)
            ->pluck('id', 'url')
            ->all();

        $leftover = array_values(array_filter(
            $urls,
            static fn (string $url): bool => !array_key_exists($url, $shopBookByUrl)
        ));
        $discoveredByUrl = [];
        if ($leftover !== []) {
            // discovered_urls is keyed on the normalised form, so the raw URL
            // has to go through the same normalisation to match.
            $normalised = [];
            foreach ($leftover as $url) {
                $normalised[UrlUtils::normalize($url)] = $url;
            }
            $rows = DB::table('discovered_urls')
                ->where('shop_id', $shopId)
                ->whereIn('normalized_url', array_keys($normalised))
                ->pluck('id', 'normalized_url')
                ->all();
            foreach ($rows as $normalisedUrl => $id) {
                $raw = $normalised[$normalisedUrl] ?? null;
                if ($raw !== null) {
                    $discoveredByUrl[$raw] = $id;
                }
            }
        }

        foreach ($issues as $index => $issue) {
            if (($issue['shop_book_id'] ?? null) !== null
                || ($issue['discovered_url_id'] ?? null) !== null) {
                continue;
            }
            $url = (string) ($issue['url'] ?? '');
            if (isset($shopBookByUrl[$url])) {
                $issues[$index]['shop_book_id'] = (int) $shopBookByUrl[$url];
            } elseif (isset($discoveredByUrl[$url])) {
                $issues[$index]['discovered_url_id'] = (int) $discoveredByUrl[$url];
            }
        }

        return $issues;
    }

    /**
     * On first detection: insert as `new` (or whatever initial_state the
     * check asked for), run_count 1. On re-detection: bump run_count, and
     * revive a resolved row. A snoozed row whose snooze has expired goes
     * back to `new`.
     *
     * @param list<array<string, mixed>> $batch
     */
    private function upsertBatch(array $batch, int $shopId, int $runId, string $conflictTarget): void
    {
        if ($batch === []) {
            return;
        }

        $now = Carbon::now('UTC');

        // Chunked: a first validate run on a large shop can emit thousands of
        // issues, and each row binds 12 parameters.
        foreach (array_chunk($batch, 500) as $chunk) {
            $rows = [];
            $bindings = [];
            foreach ($chunk as $issue) {
                // slug_diacritic_loss starts acknowledged: the bug is in the
                // shop's slug generator and we will never fix it, so it must
                // not sit in the operator's "new" queue.
                $state = (string) ($issue['initial_state'] ?? 'new');
                $rows[] = '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)';
                array_push(
                    $bindings,
                    $shopId,
                    $runId,
                    $runId,
                    (string) ($issue['url'] ?? ''),
                    (string) ($issue['field'] ?? ''),
                    (string) ($issue['issue'] ?? ''),
                    $issue['raw_value'] ?? null,
                    $issue['shop_book_id'] ?? null,
                    $issue['discovered_url_id'] ?? null,
                    $state,
                    // Mirrors manual acknowledgement so queries filtering on
                    // `acknowledged_at IS NOT NULL` see auto-acked issues too.
                    $state === 'acknowledged' ? $now : null,
                );
            }

            DB::statement(
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

    /**
     * Close every open issue this run didn't re-emit. This is why a typo'd
     * issue key is dangerous: it silently resolves a real backlog and opens
     * a bogus one under the misspelling.
     */
    public function resolveGone(int $shopId, int $runId): int
    {
        return DB::table('validation_issues')
            ->where('shop_id', $shopId)
            ->where('last_seen_run_id', '!=', $runId)
            ->whereIn('lifecycle_state', self::OPEN_STATES)
            ->update([
                'lifecycle_state' => 'resolved',
                'resolved_at' => Carbon::now('UTC'),
            ]);
    }
}
