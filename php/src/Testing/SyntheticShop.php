<?php

declare(strict_types=1);

namespace BookScraper\Testing;

use Illuminate\Database\Connection;
use RuntimeException;

/**
 * A shop built from nothing that fires every validator check.
 *
 * Port of php/tools/synthesize_validate_cases.py, which must outlive Python:
 * the validator's findings can only be frozen over data that is reproducible,
 * and a copied real shop is not — seed_test_db.py copies from the main
 * catalogue, which moves with every crawl, so the counts would drift and the
 * characterisation test would fail for reasons that are not regressions.
 *
 * These 26 rows produce the same 33 findings every time, across all 20 issue
 * types, including the suppression cases — which matter as much as the
 * positives, since most of this validator's history is noise reduction.
 *
 * Writes, so it refuses any database that is not clearly a test target.
 */
final class SyntheticShop
{
    public const SHOP = 'synthetic';

    private const BASE = 'https://synthetic.test';

    /** Author name used by the match case, on both sides of the link. */
    private const AUTHOR = 'Synthetic Canonical Author';

    /**
     * Every ISBN the fixture uses, in a 979-0 block no book catalogue reaches
     * (979-0 is ISMN space — printed music).
     *
     * The first draft used plausible 978-609 Lithuanian numbers, three of
     * which existed in the copied catalogue. The matcher linked them, so the
     * linkage this fixture produced depended on the copy and could not be
     * frozen. assertNoIsbnCollision() now fails loudly if that ever recurs.
     */
    private const ISBN = [
        'nonbook' => '9790000000015',
        'nonbook_puzzle' => '9790000000022',
        'nonbook_dvd' => '9790000000039',
        'dup' => '9790000000046',
        'drift_shop' => '9790000000053',
        'drift_canonical' => '9790000000060',
        'matchable' => '9790000000077',
    ];

    /** The `postgres-test` compose service. 5432 is the real catalogue. */
    private const TEST_PORT = 5433;

    /**
     * Every row, as [slug, overrides]. Keys starting with `_` steer the
     * builder; the rest are column values.
     *
     * Each book is active, in stock, freshly seen and priced unless the case
     * under test needs otherwise, so a row trips the check it is named for.
     *
     * @return list<array{0: string, 1: array<string, mixed>}>
     */
    private static function cases(): array
    {
        return [
            // format_is_dimensions: format looks like a dimension expression.
            ['dims-a', ['format' => '17x24']],
            ['dims-b', ['format' => '170 x 205 mm']],
            // …and the shape that must NOT fire.
            ['dims-ok', ['format' => 'paperback']],

            // non_book_has_isbn: type=non_book carrying a real 978 ISBN.
            ['nonbook-isbn', ['type' => 'non_book', 'isbn' => self::ISBN['nonbook']]],
            // Suppressed: category marks it a legitimate non-book product.
            ['nonbook-isbn-puzzle', [
                'type' => 'non_book', 'isbn' => self::ISBN['nonbook_puzzle'],
                'categories' => ['Žaislai', 'Dėlionės'],
            ]],
            // Suppressed: title marks it a DVD.
            ['nonbook-isbn-dvd', [
                'type' => 'non_book', 'isbn' => self::ISBN['nonbook_dvd'],
                'title' => 'Something (DVD)',
            ]],
            // Not flagged: a plain EAN on a non-book is just a GTIN.
            ['nonbook-ean', ['type' => 'non_book', 'isbn' => '4001234567890']],

            // orphan_no_url: no discovered_urls row at all.
            ['orphan', ['_no_url' => true]],

            // non_product_active: one non_product URL beside a good one, so
            // the auto-heal leaves it active and it gets flagged.
            ['mixed-nonproduct', ['_extra_urls' => [['non_product', 'mixed-nonproduct-alt']]]],
            // All URLs non_product -> auto-healed to inactive, NOT flagged.
            ['all-nonproduct', ['_url_type' => 'non_product']],

            // unreachable_active: active book whose URL is unreachable.
            ['unreachable', ['_url_type' => 'unreachable']],

            // isbn_duplicate: two live books sharing an ISBN. Both sides are
            // flagged, so this is two issues, not one.
            ['dup-isbn-a', ['isbn' => self::ISBN['dup']]],
            ['dup-isbn-b', ['isbn' => self::ISBN['dup']]],

            // title_author_duplicate: same title and author, both ISBNs NULL
            // (the check pairs on equal-or-both-null ISBN).
            ['dup-ta-a', ['title' => 'Duplicate Title', 'author' => 'Same Author']],
            ['dup-ta-b', ['title' => 'Duplicate Title', 'author' => 'Same Author']],

            // Three at once, deliberately: a live book with no price and no
            // price row trips active_no_price, in_stock_no_price and
            // no_price_history together. The first two share a predicate —
            // kept as separate issue types for operators' acknowledgements.
            ['no-price', ['price' => null, '_no_price' => true]],

            // price_zero: priced at zero while active and in stock.
            ['price-zero', ['price' => '0.00']],

            // year_out_of_range: both ends of the window (< 1800, > now + 2).
            ['year-ancient', ['year' => 1500]],
            ['year-future', ['year' => 2099]],

            // book_no_metadata alone: no isbn/author/year, but a format, so
            // the no-signals check (format IS NULL too) stays quiet.
            ['no-metadata', ['author' => null, 'year' => null, 'format' => 'paperback']],
            // book_no_metadata AND book_no_signals: nothing identifies it.
            ['no-signals', ['author' => null, 'year' => null]],
            // Suppressed: the title marks it a DVD, so having no book
            // metadata is expected rather than a defect.
            ['no-metadata-dvd', [
                'author' => null, 'year' => null, 'title' => 'Something Else (DVD)',
            ]],

            // stale_active: last seen far past 2 * STALE_CADENCE_DAYS. A
            // FIXED date, not now()-60d: this row's last_seen_at is reported
            // as the issue's raw_value, so a relative one would differ on
            // every rebuild and no golden could hold it.
            ['stale', ['_last_seen_at' => '2020-01-01 00:00:00+00']],

            // slug_title_mismatch: slug and title share no tokens at all.
            ['zzz-qqq-xxx', ['title' => 'Completely Different Book']],

            // slug_diacritic_loss: `kale`+`du` re-merges to the folded
            // `Kalėdų`, the signature of a slug generator dropping diacritics
            // per character. Also suppresses slug_title_mismatch on this row
            // (zero token overlap would otherwise flag it), which is what
            // exercises supersession.
            ['kale-du-pu-ga', ['title' => 'Kalėdų pūga']],

            // Matcher step 1 (ISBN link) and step 2 (author backfill): a
            // canonical carrying the SAME ISBN and an author at position 0,
            // with a shop_author at the same position to be backfilled.
            ['matchable', [
                'isbn' => self::ISBN['matchable'],
                'author' => self::AUTHOR,
                '_canonical_match' => true,
            ]],

            // match_isbn_drift: linked to a canonical whose ISBN disagrees.
            // Not a matcher bug — the shop_book's ISBN mutated after linking.
            ['drift', [
                'isbn' => self::ISBN['drift_shop'],
                '_canonical_isbn' => self::ISBN['drift_canonical'],
            ]],
        ];
    }

    /** @return array<string, mixed> */
    private static function defaults(): array
    {
        return [
            'title' => null,
            'author' => 'Synthetic Author',
            'isbn' => null,
            'sku' => null,
            'publisher' => 'Synthetic Press',
            'year' => 2024,
            'format' => null,
            'type' => 'book',
            'price' => '9.99',
            'in_stock' => true,
            'is_active' => true,
            'categories' => ['Grožinė literatūra'],
        ];
    }

    /**
     * Rebuild the shop from scratch. Idempotent: everything it created last
     * time is removed first, so findings do not accumulate across runs.
     *
     * @return array{shop_id: int, rows: int}
     */
    public static function build(Connection $db): array
    {
        self::guard($db);

        $shopId = $db->transaction(function () use ($db): int {
            self::clear($db);
            self::assertNoIsbnCollision($db);

            return (int) $db->selectOne(
                'insert into shops (name, base_url) values (?, ?) '
                . 'on conflict (name) do update set base_url = excluded.base_url '
                . 'returning id',
                [self::SHOP, self::BASE]
            )->id;
        });

        $cases = self::cases();

        $db->transaction(function () use ($db, $shopId, $cases): void {
            foreach ($cases as [$slug, $overrides]) {
                self::insertCase($db, $shopId, $slug, $overrides);
            }
            self::insertRunFixtures($db, $shopId);
        });

        return ['shop_id' => $shopId, 'rows' => count($cases)];
    }

    /**
     * A run, its queue items, a cron job and one issue.
     *
     * The validator ignores all four, so they cannot move its findings — but
     * the dashboard's run, cron and issue detail routes cannot be exercised
     * without them, and after a reseed these tables are empty (seed_test_db
     * deliberately copies no runs). Values are deliberately non-null where the
     * column allows null, so the frozen API shapes pin real types rather than
     * "null".
     */
    private static function insertRunFixtures(Connection $db, int $shopId): void
    {
        $runId = (int) $db->selectOne(
            'insert into scrape_runs (shop_id, phase, status, started_at, finished_at, '
            . 'urls_total, urls_processed, items_added, items_updated, errors_4xx, '
            . 'errors_5xx, error_count, last_heartbeat, pid, resumable_after_failure, '
            . "close_reason) values (?, 'scan', 'completed', now() - make_interval(mins => 30), "
            . "now() - make_interval(mins => 5), 26, 26, 20, 6, 1, 1, 2, "
            . "now() - make_interval(mins => 5), 4242, false, 'finished') returning id",
            [$shopId]
        )->id;

        $urls = $db->select(
            'select id, url from discovered_urls where shop_id = ? order by id limit 3',
            [$shopId]
        );
        // One row per terminal state, so the queue-filtered endpoints
        // (?status=done, ?status=failed) return rows rather than empty lists.
        $states = [
            ['done', 200, 12_345],
            ['failed', 500, 0],
            ['pending', null, null],
        ];
        foreach ($urls as $i => $url) {
            [$status, $httpStatus, $bytes] = $states[$i] ?? $states[0];
            $db->statement(
                'insert into scrape_url_items (run_id, shop_id, discovered_url_id, url, '
                . 'status, created_at, claimed_at, done_at, url_type, http_status, '
                . "request_delay_s, delay_source, retry_count, response_bytes, attempts) "
                . "values (?, ?, ?, ?, ?, now() - make_interval(mins => 30), "
                . "now() - make_interval(mins => 29), now() - make_interval(mins => 28), "
                . "'product', ?, 0.5, 'shop_settings', 0, ?, 1)",
                [$runId, $shopId, $url->id, $url->url, $status, $httpStatus, $bytes]
            );
        }

        $db->statement(
            'insert into cron_jobs (shop_id, phase, strategy, args, cron_expression, '
            . "enabled, last_run_at, created_at) values (?, 'discover', 'sitemap', '', "
            . "'0 3 * * *', true, now() - make_interval(days => 1), now())",
            [$shopId]
        );

        // One issue so /api/issues/{id} has something to show. Whoever
        // measures the VALIDATOR's findings must delete it first — see the
        // note in ValidateServiceCharacterisationTest.
        $book = $db->selectOne(
            'select id, url from shop_books where shop_id = ? order by id limit 1',
            [$shopId]
        );
        $db->statement(
            'insert into validation_issues (last_seen_run_id, url, field, issue, raw_value, '
            . 'shop_book_id, lifecycle_state, shop_id, first_seen_run_id, run_count) '
            . "values (?, ?, 'format', 'format_is_dimensions', '17x24', ?, 'new', ?, ?, 1)",
            [$runId, $book->url, $book->id, $shopId, $runId]
        );
    }

    /** Everything a previous build created, in reference order. */
    private static function clear(Connection $db): void
    {
        // EVERY issue, not just this shop's. The dashboard's issue lists and
        // counts read across all shops, so the frozen API shapes are only
        // reproducible if the fixture defines the whole issue set — otherwise
        // a `validate-diff vaga` run beforehand leaves 13,339 rows and the
        // first row of /api/issues is a different shape entirely.
        //
        // Safe because this only ever runs against a test database (see
        // guard()), and because validation_issues is derived data: a validate
        // run rebuilds it from scratch.
        $db->statement('delete from validation_issues');
        $db->statement(
            'delete from scrape_url_items where shop_id in '
            . '(select id from shops where name = ?)',
            [self::SHOP]
        );
        $db->statement(
            'delete from cron_jobs where shop_id in (select id from shops where name = ?)',
            [self::SHOP]
        );
        $db->statement(
            'delete from scrape_runs where shop_id in (select id from shops where name = ?)',
            [self::SHOP]
        );
        foreach (['prices', 'shop_book_attributes', 'shop_book_authors', 'shop_book_changes'] as $table) {
            $db->statement(
                "delete from {$table} where shop_book_id in (select sb.id from shop_books sb "
                . 'join shops s on s.id = sb.shop_id where s.name = ?)',
                [self::SHOP]
            );
        }
        $db->statement(
            'delete from discovered_urls where shop_id in (select id from shops where name = ?)',
            [self::SHOP]
        );
        $db->statement(
            'delete from shop_books where shop_id in (select id from shops where name = ?)',
            [self::SHOP]
        );
        // The canonical the drift case disagrees with. Deleted after the
        // shop_books referencing it, and found by source_url — books carry no
        // shop of their own.
        $db->statement(
            'delete from book_isbns where book_id in (select id from books where source_url like ?)',
            [self::BASE . '/%']
        );
        $db->statement(
            'delete from book_authors where book_id in '
            . '(select id from books where source_url like ?)',
            [self::BASE . '/%']
        );
        $db->statement('delete from books where source_url like ?', [self::BASE . '/%']);
        $db->statement('delete from shop_authors where name = ?', [self::AUTHOR]);
        $db->statement('delete from authors where name = ?', [self::AUTHOR]);
    }

    /**
     * Fail if any fixture ISBN already belongs to a canonical this fixture
     * does not own.
     *
     * Called after clear(), so anything still holding one is foreign — and a
     * foreign canonical would make the matcher link a fixture book, changing
     * the linkage the golden froze.
     */
    private static function assertNoIsbnCollision(Connection $db): void
    {
        $clash = $db->select(
            'select isbn from book_isbns where isbn in ('
            . implode(',', array_fill(0, count(self::ISBN), '?')) . ')',
            array_values(self::ISBN)
        );
        if ($clash !== []) {
            throw new RuntimeException(sprintf(
                'refusing to build: %s already exist(s) in book_isbns. The fixture '
                . 'ISBNs must belong to nothing else, or the matcher links these '
                . 'books to a canonical the fixture does not control.',
                implode(', ', array_map(static fn ($r) => $r->isbn, $clash))
            ));
        }
    }

    /** @param array<string, mixed> $overrides */
    private static function insertCase(
        Connection $db,
        int $shopId,
        string $slug,
        array $overrides
    ): void {
        $row = self::defaults();
        foreach ($overrides as $key => $value) {
            if (! str_starts_with($key, '_')) {
                $row[$key] = $value;
            }
        }
        $row['title'] ??= ucwords(str_replace('-', ' ', $slug));
        $url = self::BASE . '/' . $slug;

        $bookId = (int) $db->selectOne(
            'insert into shop_books (shop_id, url, title, author, isbn, sku, publisher, '
            . 'year, format, type, price, in_stock, is_active, categories, match_status, '
            . 'first_seen_at, last_seen_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '
            . "'unmatched', now(), coalesce(?::timestamptz, now())) returning id",
            [
                $shopId, $url, $row['title'], $row['author'], $row['isbn'], $row['sku'],
                $row['publisher'], $row['year'], $row['format'], $row['type'], $row['price'],
                $row['in_stock'], $row['is_active'], self::pgArray($row['categories']),
                $overrides['_last_seen_at'] ?? null,
            ]
        )->id;

        if (isset($overrides['_canonical_isbn'])) {
            $canonical = (int) $db->selectOne(
                'insert into books (data_source, title, upcoming_release, created_at, '
                . "updated_at, source_url) values ('shop_inferred', ?, false, now(), now(), ?) "
                . 'returning id',
                [$row['title'], self::BASE . '/canonical/' . $slug]
            )->id;
            $db->statement(
                "insert into book_isbns (book_id, isbn, isbn_type) values (?, ?, 'isbn13')",
                [$canonical, $overrides['_canonical_isbn']]
            );
            $db->statement(
                "update shop_books set book_id = ?, match_status = 'matched' where id = ?",
                [$canonical, $bookId]
            );
        }

        if ($overrides['_canonical_match'] ?? false) {
            $canonical = (int) $db->selectOne(
                'insert into books (data_source, title, upcoming_release, created_at, '
                . "updated_at, source_url) values ('shop_inferred', ?, false, now(), now(), ?) "
                . 'returning id',
                [$row['title'], self::BASE . '/canonical/' . $slug]
            )->id;
            $db->statement(
                "insert into book_isbns (book_id, isbn, isbn_type) values (?, ?, 'isbn13')",
                [$canonical, $row['isbn']]
            );
            $authorId = (int) $db->selectOne(
                'insert into authors (name, normalized_name, created_at) '
                . 'values (?, ?, now()) returning id',
                [self::AUTHOR, mb_strtolower(self::AUTHOR)]
            )->id;
            $db->statement(
                "insert into book_authors (book_id, author_id, role, position) "
                . "values (?, ?, 'author', 0)",
                [$canonical, $authorId]
            );
            // Left unlinked on purpose: linking it is what step 2 does.
            $shopAuthor = (int) $db->selectOne(
                'insert into shop_authors (name, normalized_name, created_at) '
                . 'values (?, ?, now()) returning id',
                [self::AUTHOR, mb_strtolower(self::AUTHOR)]
            )->id;
            $db->statement(
                'insert into shop_book_authors (shop_book_id, author_id, position) '
                . 'values (?, ?, 0)',
                [$bookId, $shopAuthor]
            );
        }

        if ($overrides['_no_url'] ?? false) {
            return;
        }

        self::insertUrl($db, $shopId, $url, $overrides['_url_type'] ?? 'product', $bookId);
        foreach ($overrides['_extra_urls'] ?? [] as [$urlType, $altSlug]) {
            self::insertUrl($db, $shopId, self::BASE . '/' . $altSlug, $urlType, $bookId);
        }

        // A price row keeps no_price_history from firing on every book —
        // except where its absence is the case under test.
        if ($overrides['_no_price'] ?? false) {
            return;
        }
        $db->statement(
            'insert into prices (shop_book_id, price, in_stock, scraped_at) '
            . 'values (?, ?, ?, now())',
            [$bookId, $row['price'], $row['in_stock']]
        );
    }

    private static function insertUrl(
        Connection $db,
        int $shopId,
        string $url,
        string $urlType,
        int $bookId
    ): void {
        $db->statement(
            'insert into discovered_urls (shop_id, url, normalized_url, source, url_type, '
            . "fail_count, first_seen_at, last_seen_at, shop_book_id) values (?, ?, ?, 'sitemap', "
            . '?, 0, now(), now(), ?)',
            [$shopId, $url, $url, $urlType, $bookId]
        );
    }

    /** @param list<string> $values */
    private static function pgArray(array $values): string
    {
        return '{' . implode(',', array_map(
            static fn (string $v): string => '"' . str_replace(['\\', '"'], ['\\\\', '\"'], $v) . '"',
            $values
        )) . '}';
    }

    /**
     * Refuse anything that is not clearly a test database.
     *
     * The port check is the load-bearing one: the real catalogue is the only
     * thing on 5432, so a builder that never accepts 5432 cannot damage it
     * however wrong its other arguments are.
     */
    private static function guard(Connection $db): void
    {
        $port = (int) ($db->getConfig('port') ?? 0);
        $name = (string) ($db->getConfig('database') ?? '');

        if ($port !== self::TEST_PORT) {
            throw new RuntimeException(sprintf(
                'refusing to build: %s is on port %d, not the test cluster (%d). '
                . 'The real catalogue is on 5432.',
                $name !== '' ? $name : '<unnamed>',
                $port,
                self::TEST_PORT
            ));
        }
        if (! str_contains($name, 'test')) {
            throw new RuntimeException(
                "refusing to build: database '{$name}' is not named as a test database."
            );
        }
    }
}
