<?php

declare(strict_types=1);

namespace BookScraper\Services;

use Illuminate\Support\Facades\DB;
use RuntimeException;

/**
 * Per-shop data-quality validator, ported from
 * book_scraper/services/validate.py. Checks are SQL-driven and idempotent.
 *
 * The SQL is carried over verbatim; only the surrounding control flow and
 * the Python post-filters are rewritten. Suppression rules exist because of
 * measured false-positive classes — see ValidateHelpers.
 */
final class ValidateService
{
    /** Doubled to give a shop a full missed cadence before flagging. */
    private const STALE_CADENCE_DAYS = 14;

    /**
     * Every issue key this service can emit.
     *
     * resolveGone() closes anything the current run didn't re-emit, so a
     * typo'd key silently resolves a real backlog and opens a bogus one.
     * run() asserts against this set so the typo fails loudly instead.
     */
    public const ISSUE_KEYS = [
        'active_no_price',
        'book_no_metadata',
        'book_no_signals',
        'format_is_dimensions',
        'in_stock_no_price',
        'isbn_duplicate',
        'match_isbn_drift',
        'no_price_history',
        'non_book_has_isbn',
        'non_product_active',
        'orphan_no_url',
        'price_zero',
        'sku_duplicate',
        'slug_diacritic_loss',
        'slug_title_mismatch',
        'stale_active',
        'title_author_duplicate',
        'unmatched_has_isbn',
        'unreachable_active',
        'url_aliases',
        'year_out_of_range',
    ];

    public function __construct(
        private readonly ValidationIssueWriter $writer = new ValidationIssueWriter(),
    ) {}

    /**
     * Run every check group, persist findings, close what's gone.
     *
     * @return array<string, int> counts keyed by issue key
     */
    public function run(int $shopId, int $runId): array
    {
        $issues = [
            ...$this->checkStructuralDuplicates($shopId, $runId),
            ...$this->checkSlugTitleMismatch($shopId, $runId),
            ...$this->checkSlugDiacriticLoss($shopId, $runId),
            ...$this->checkDataCompleteness($shopId, $runId),
            ...$this->checkDataCorrectness($shopId, $runId),
            ...$this->checkClassificationConsistency($shopId, $runId),
            ...$this->checkStaleness($shopId, $runId),
            ...$this->checkMatchReadiness($shopId, $runId),
            ...$this->checkRelationshipIntegrity($shopId, $runId),
        ];

        $this->writer->upsert($issues, $shopId, $runId);
        $this->writer->resolveGone($shopId, $runId);

        $counters = [];
        foreach ($issues as $issue) {
            $key = (string) $issue['issue'];
            $counters[$key] = ($counters[$key] ?? 0) + 1;
        }

        $unknown = array_diff(array_keys($counters), self::ISSUE_KEYS);
        if ($unknown !== []) {
            throw new RuntimeException(
                'validator emitted unregistered issue key(s): '
                . implode(', ', $unknown)
                . ' — add them to ISSUE_KEYS and to ISSUE_DESCRIPTIONS in the dashboard, '
                . 'or fix the typo'
            );
        }

        ksort($counters);

        return $counters;
    }

    /**
     * The mandatory `shop_books` WHERE prefix: shop scope plus gates.
     *
     * Every validator reads only the LIVE catalogue. A delisted row is not a
     * data-quality problem, it's gone. Price checks additionally require
     * in_stock, because an out-of-stock book legitimately has no price.
     *
     * Building the clause here is the point: seven checks had drifted without
     * a gate, each reopening noise on delisted rows every run.
     */
    private static function liveBooks(string $alias = '', bool $inStock = false): string
    {
        $prefix = $alias !== '' ? "{$alias}." : '';
        $clauses = ["{$prefix}shop_id = ?", "{$prefix}is_active = true"];
        if ($inStock) {
            $clauses[] = "{$prefix}in_stock = true";
        }

        return implode(' AND ', $clauses);
    }

    // ------------------------------------------------- structural duplicates

    /**
     * Both rows of each pair get an issue. `is_active` is required on BOTH
     * sides: deactivating one row of a duplicate pair resolves the issue by
     * definition, and without the second gate historical dedup work never
     * clears the backlog.
     *
     * @return list<array<string, mixed>>
     */
    public function checkStructuralDuplicates(int $shopId, int $runId): array
    {
        $results = [];

        // Only real ISBNs: stale '' values predate the pipeline's null-out.
        foreach (DB::select(
            'select sb.id, sb.url, sb.isbn from shop_books sb
             where ' . self::liveBooks('sb') . "
               and sb.isbn is not null and sb.isbn != ''
               and exists (
                   select 1 from shop_books sb2
                   where " . self::liveBooks('sb2') . '
                     and sb2.isbn = sb.isbn and sb2.id != sb.id
               )',
            [$shopId, $shopId]
        ) as $row) {
            $results[] = self::issue($runId, $row->url, 'isbn', 'isbn_duplicate', $row->isbn, $row->id);
        }

        // Same title+author with DIFFERENT ISBNs is a legitimate re-edition,
        // so only flag when the ISBNs match too (or are both null).
        foreach (DB::select(
            'select sb.id, sb.url, sb.title, sb.author from shop_books sb
             where ' . self::liveBooks('sb') . '
               and sb.title is not null and sb.author is not null
               and exists (
                   select 1 from shop_books sb2
                   where ' . self::liveBooks('sb2') . '
                     and lower(sb2.title) = lower(sb.title)
                     and lower(sb2.author) = lower(sb.author)
                     and sb2.id != sb.id
                     and (sb2.isbn = sb.isbn or (sb2.isbn is null and sb.isbn is null))
               )',
            [$shopId, $shopId]
        ) as $row) {
            $results[] = self::issue(
                $runId, $row->url, 'title_author', 'title_author_duplicate',
                "{$row->title} / {$row->author}", $row->id
            );
        }

        foreach (DB::select(
            'select sb.id, sb.url, sb.sku from shop_books sb
             where ' . self::liveBooks('sb') . '
               and sb.sku is not null
               and exists (
                   select 1 from shop_books sb2
                   where ' . self::liveBooks('sb2') . '
                     and sb2.sku = sb.sku and sb2.id != sb.id
               )',
            [$shopId, $shopId]
        ) as $row) {
            $results[] = self::issue($runId, $row->url, 'sku', 'sku_duplicate', $row->sku, $row->id);
        }

        return $results;
    }

    // -------------------------------------------------------------- slug

    /** @return list<array<string, mixed>> */
    public function checkSlugTitleMismatch(int $shopId, int $runId): array
    {
        $results = [];
        foreach ($this->titledBooks($shopId) as $row) {
            $slug = ValidateHelpers::slugFromUrl($row->url);
            if (!ValidateHelpers::shouldFlagSlugTitle($slug, $row->title)) {
                continue;
            }
            // Supersession: when diacritic loss explains the mismatch, only
            // the more specific issue fires. The historical broad issue then
            // auto-closes because this run no longer re-emits it.
            if (ValidateHelpers::looksDiacriticLossy($slug, $row->title)) {
                continue;
            }
            $results[] = self::issue($runId, $row->url, 'slug', 'slug_title_mismatch', $slug, $row->id);
        }

        return $results;
    }

    /** @return list<array<string, mixed>> */
    public function checkSlugDiacriticLoss(int $shopId, int $runId): array
    {
        $results = [];
        foreach ($this->titledBooks($shopId) as $row) {
            $slug = ValidateHelpers::slugFromUrl($row->url);
            if (!ValidateHelpers::looksDiacriticLossy($slug, $row->title)) {
                continue;
            }
            $issue = self::issue($runId, $row->url, 'slug', 'slug_diacritic_loss', $slug, $row->id);
            // The shop's slug generator is the bug and we will never fix it,
            // so this must never land in the operator's "new" queue.
            $issue['initial_state'] = 'acknowledged';
            $results[] = $issue;
        }

        return $results;
    }

    private function titledBooks(int $shopId): array
    {
        return DB::select(
            'select id, url, title from shop_books
             where ' . self::liveBooks() . ' and title is not null',
            [$shopId]
        );
    }

    // ------------------------------------------------------- completeness

    /** @return list<array<string, mixed>> */
    public function checkDataCompleteness(int $shopId, int $runId): array
    {
        $results = [];

        // active_no_price and in_stock_no_price share a predicate since the
        // in_stock gate was added. Kept as distinct keys so existing operator
        // acknowledgements stay attached to the key they were made against.
        foreach (['active_no_price', 'in_stock_no_price'] as $key) {
            foreach (DB::select(
                'select id, url from shop_books
                 where ' . self::liveBooks('', true) . ' and price is null',
                [$shopId]
            ) as $row) {
                $results[] = self::issue($runId, $row->url, 'price', $key, null, $row->id);
            }
        }

        // A DVD or box-set in patogupirkti's /knyga/ path legitimately lacks
        // ISBN/author/year, so the non-book markers suppress it.
        foreach (DB::select(
            "select id, url, title, categories from shop_books
             where " . self::liveBooks() . " and type = 'book'
               and isbn is null and author is null and year is null",
            [$shopId]
        ) as $row) {
            if ($this->looksNonBook($row)) {
                continue;
            }
            $results[] = self::issue($runId, $row->url, 'metadata', 'book_no_metadata', null, $row->id);
        }

        foreach (DB::select(
            'select sb.id, sb.url from shop_books sb
             left join prices p on p.shop_book_id = sb.id
             where ' . self::liveBooks('sb', true) . ' and p.id is null',
            [$shopId]
        ) as $row) {
            $results[] = self::issue($runId, $row->url, 'price_history', 'no_price_history', null, $row->id);
        }

        return $results;
    }

    // -------------------------------------------------------- correctness

    /** @return list<array<string, mixed>> */
    public function checkDataCorrectness(int $shopId, int $runId): array
    {
        $results = [];

        foreach (DB::select(
            'select id, url, year from shop_books
             where ' . self::liveBooks() . ' and year is not null
               and (year < 1800 or year > extract(year from now())::int + 2)',
            [$shopId]
        ) as $row) {
            $results[] = self::issue($runId, $row->url, 'year', 'year_out_of_range', (string) $row->year, $row->id);
        }

        // Out-of-stock items on some shops (pegasas) legitimately report
        // price=0 when no listing price exists, hence the in_stock gate.
        foreach (DB::select(
            'select id, url from shop_books
             where ' . self::liveBooks('', true) . ' and price = 0',
            [$shopId]
        ) as $row) {
            $results[] = self::issue($runId, $row->url, 'price', 'price_zero', '0', $row->id);
        }

        foreach (DB::select(
            'select id, url, format from shop_books
             where ' . self::liveBooks() . " and format is not null
               and format ~ '^\\d+.*[xX×].*\\d+'",
            [$shopId]
        ) as $row) {
            $results[] = self::issue($runId, $row->url, 'format', 'format_is_dimensions', $row->format, $row->id);
        }

        return $results;
    }

    // ---------------------------------------------------- classification

    /** @return list<array<string, mixed>> */
    public function checkClassificationConsistency(int $shopId, int $runId): array
    {
        $results = [];

        foreach (DB::select(
            "select id, url, title, categories from shop_books
             where " . self::liveBooks() . " and type = 'book'
               and isbn is null and author is null
               and year is null and format is null",
            [$shopId]
        ) as $row) {
            if ($this->looksNonBook($row)) {
                continue;
            }
            $results[] = self::issue($runId, $row->url, 'type', 'book_no_signals', null, $row->id);
        }

        // Only 978/979 ISBNs: a plain EAN on a non-book is just a GTIN.
        // Many LT publishers register puzzles, board games and notebooks
        // under a real ISBN, so the non-book markers suppress those.
        foreach (DB::select(
            "select id, url, isbn, title, categories from shop_books
             where " . self::liveBooks() . " and type = 'non_book'
               and isbn is not null and isbn ~ '^97[89]'",
            [$shopId]
        ) as $row) {
            if ($this->looksNonBook($row)) {
                continue;
            }
            $results[] = self::issue($runId, $row->url, 'type', 'non_book_has_isbn', $row->isbn, $row->id);
        }

        // Auto-heal: when EVERY one of a book's URLs is non_product, the scan
        // has confirmed the listing is gone, so deactivate rather than flag.
        // That's ~99% of these (1,945 rows in the 2026-05-17 pegasas cleanup).
        DB::update(
            'update shop_books sb
             set is_active = false, inactive_since = now()
             where ' . self::liveBooks('sb') . "
               and not exists (
                   select 1 from discovered_urls du
                   where du.shop_book_id = sb.id and du.url_type != 'non_product'
               )
               and exists (
                   select 1 from discovered_urls du
                   where du.shop_book_id = sb.id and du.url_type = 'non_product'
               )",
            [$shopId]
        );

        // Only the residual mixed cases need a human.
        foreach (DB::select(
            'select sb.id, sb.url from shop_books sb
             join discovered_urls du on du.shop_book_id = sb.id
             where ' . self::liveBooks('sb') . " and du.url_type = 'non_product'",
            [$shopId]
        ) as $row) {
            $results[] = self::issue($runId, $row->url, 'url_type', 'non_product_active', 'non_product', $row->id);
        }

        return $results;
    }

    // --------------------------------------------------------- staleness

    /** @return list<array<string, mixed>> */
    public function checkStaleness(int $shopId, int $runId): array
    {
        $results = [];
        $days = 2 * self::STALE_CADENCE_DAYS;

        foreach (DB::select(
            'select id, url, last_seen_at from shop_books
             where ' . self::liveBooks() . '
               and last_seen_at < now() - make_interval(days => ?)',
            [$shopId, $days]
        ) as $row) {
            $results[] = self::issue(
                $runId, $row->url, 'last_seen_at', 'stale_active',
                self::isoTimestamp($row->last_seen_at), $row->id
            );
        }

        foreach (DB::select(
            'select sb.id, sb.url from shop_books sb
             join discovered_urls du on du.shop_book_id = sb.id
             where ' . self::liveBooks('sb') . " and du.url_type = 'unreachable'",
            [$shopId]
        ) as $row) {
            $results[] = self::issue($runId, $row->url, 'url_type', 'unreachable_active', 'unreachable', $row->id);
        }

        foreach (DB::select(
            'select sb.id, sb.url from shop_books sb
             left join discovered_urls du on du.shop_book_id = sb.id
             where ' . self::liveBooks('sb') . ' and du.id is null',
            [$shopId]
        ) as $row) {
            $results[] = self::issue($runId, $row->url, 'url', 'orphan_no_url', $row->url, $row->id);
        }

        return $results;
    }

    // ---------------------------------------------------- match readiness

    /** @return list<array<string, mixed>> */
    public function checkMatchReadiness(int $shopId, int $runId): array
    {
        $results = [];

        foreach (DB::select(
            'select id, url, isbn from shop_books
             where ' . self::liveBooks() . " and match_status = 'unmatched'
               and isbn is not null",
            [$shopId]
        ) as $row) {
            $results[] = self::issue($runId, $row->url, 'match_status', 'unmatched_has_isbn', $row->isbn, $row->id);
        }

        // A book can carry both ISBN-13 and ISBN-10, so drift means the
        // shop's ISBN matches NONE of the canonical's. The substring
        // comparisons treat '9789986092476' and '9986092476' as equivalent —
        // they share the 9-digit body.
        foreach (DB::select(
            'select sb.id, sb.url, sb.isbn as sb_isbn,
                    (select bi2.isbn from book_isbns bi2 where bi2.book_id = b.id
                     order by bi2.isbn_type desc limit 1) as book_isbn
             from shop_books sb
             join books b on b.id = sb.book_id
             where ' . self::liveBooks('sb') . " and sb.match_status = 'matched'
               and sb.isbn is not null
               and not exists (
                   select 1 from book_isbns bi
                   where bi.book_id = b.id
                     and (
                       bi.isbn = sb.isbn
                       or (length(bi.isbn) = 10 and length(sb.isbn) = 13
                           and substring(sb.isbn, 4, 9) = substring(bi.isbn, 1, 9))
                       or (length(sb.isbn) = 10 and length(bi.isbn) = 13
                           and substring(bi.isbn, 4, 9) = substring(sb.isbn, 1, 9))
                     )
               )",
            [$shopId]
        ) as $row) {
            $results[] = self::issue(
                $runId, $row->url, 'isbn', 'match_isbn_drift',
                "{$row->sb_isbn} vs {$row->book_isbn}", $row->id
            );
        }

        return $results;
    }

    // ---------------------------------------------- relationship integrity

    /**
     * url_aliases: a book reachable at genuinely different URL shapes.
     *
     * The SQL gate drops category-prefixed variants (vaga serves /slug and
     * /cat/sub/slug — same final segment, same product). The PHP post-filter
     * then drops URL-encoding twins and OpenCart route URLs.
     *
     * @return list<array<string, mixed>>
     */
    public function checkRelationshipIntegrity(int $shopId, int $runId): array
    {
        $candidates = DB::select(
            "select sb.id, sb.url, du.url as alias_url
             from shop_books sb
             join discovered_urls du on du.shop_book_id = sb.id
             where " . self::liveBooks('sb') . "
               and rtrim(du.url, '/') != rtrim(sb.url, '/')
               and regexp_replace(rtrim(du.url, '/'), '^.+/', '')
                 != regexp_replace(rtrim(sb.url, '/'), '^.+/', '')",
            [$shopId]
        );

        $perBook = [];
        foreach ($candidates as $row) {
            if (!ValidateHelpers::isGenuineUrlAlias($row->url, $row->alias_url)) {
                continue;
            }
            if (isset($perBook[$row->id])) {
                $perBook[$row->id]['count']++;
            } else {
                $perBook[$row->id] = ['url' => $row->url, 'count' => 1];
            }
        }

        $results = [];
        foreach ($perBook as $shopBookId => $found) {
            $results[] = self::issue(
                $runId, $found['url'], 'url', 'url_aliases',
                (string) $found['count'], $shopBookId
            );
        }

        return $results;
    }

    // ----------------------------------------------------------- helpers

    /** Non-book markers, shared by the metadata and classification checks. */
    private function looksNonBook(object $row): bool
    {
        $categories = property_exists($row, 'categories') && $row->categories !== null
            ? \BookScraper\Casts\PostgresTextArray::parse((string) $row->categories)
            : null;

        return ValidateHelpers::titleIndicatesNonBook($row->title ?? null)
            || ValidateHelpers::categoriesIndicateNonBook($categories);
    }

    /** @return array<string, mixed> */
    private static function issue(
        int $runId,
        string $url,
        string $field,
        string $issue,
        ?string $rawValue,
        int $shopBookId,
    ): array {
        return [
            'scrape_run_id' => $runId,
            'url' => $url,
            'field' => $field,
            'issue' => $issue,
            'raw_value' => $rawValue,
            'shop_book_id' => $shopBookId,
        ];
    }

    /** Matches Python's datetime.isoformat() on a timestamptz column. */
    private static function isoTimestamp(?string $value): ?string
    {
        if ($value === null) {
            return null;
        }
        $dt = new \DateTimeImmutable($value);

        return $dt->format('u') === '000000'
            ? $dt->format('Y-m-d\TH:i:sP')
            : $dt->format('Y-m-d\TH:i:s.uP');
    }
}
