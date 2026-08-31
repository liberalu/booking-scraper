<?php

declare(strict_types=1);

namespace Tests\Support;

use Illuminate\Database\Connection;
use RuntimeException;

final class SyntheticShop
{
    public const SHOP = 'synthetic';

    public const SHOP_TWO = 'synthetic-two';

    private const BASE = 'https://synthetic.test';

    private const AUTHOR = 'Synthetic Canonical Author';

    private const ISBN = [
        'nonbook' => '9790000000015',
        'nonbook_puzzle' => '9790000000022',
        'nonbook_dvd' => '9790000000039',
        'dup' => '9790000000046',
        'drift_shop' => '9790000000053',
        'drift_canonical' => '9790000000060',
        'matchable' => '9790000000077',
    ];

    private const TEST_PORT = 5433;

    private static function cases(): array
    {
        return [

            ['dims-a', ['format' => '17x24']],
            ['dims-b', ['format' => '170 x 205 mm']],

            ['dims-ok', ['format' => 'paperback']],

            ['nonbook-isbn', ['type' => 'non_book', 'isbn' => self::ISBN['nonbook']]],

            ['nonbook-isbn-puzzle', [
                'type' => 'non_book', 'isbn' => self::ISBN['nonbook_puzzle'],
                'categories' => ['Žaislai', 'Dėlionės'],
            ]],

            ['nonbook-isbn-dvd', [
                'type' => 'non_book', 'isbn' => self::ISBN['nonbook_dvd'],
                'title' => 'Something (DVD)',
            ]],

            ['nonbook-ean', ['type' => 'non_book', 'isbn' => '4001234567890']],

            ['orphan', ['_no_url' => true]],

            ['mixed-nonproduct', ['_extra_urls' => [['non_product', 'mixed-nonproduct-alt']]]],

            ['all-nonproduct', ['_url_type' => 'non_product']],

            ['unreachable', ['_url_type' => 'unreachable']],

            ['dup-isbn-a', ['isbn' => self::ISBN['dup']]],
            ['dup-isbn-b', ['isbn' => self::ISBN['dup']]],

            ['dup-ta-a', ['title' => 'Duplicate Title', 'author' => 'Same Author']],
            ['dup-ta-b', ['title' => 'Duplicate Title', 'author' => 'Same Author']],

            ['no-price', ['price' => null, '_no_price' => true]],

            ['price-zero', ['price' => '0.00']],

            ['year-ancient', ['year' => 1500]],
            ['year-future', ['year' => 2099]],

            ['no-metadata', ['author' => null, 'year' => null, 'format' => 'paperback']],

            ['no-signals', ['author' => null, 'year' => null]],

            ['no-metadata-dvd', [
                'author' => null, 'year' => null, 'title' => 'Something Else (DVD)',
            ]],

            ['stale', ['_last_seen_at' => '2020-01-01 00:00:00+00']],

            ['zzz-qqq-xxx', ['title' => 'Completely Different Book']],

            ['kale-du-pu-ga', ['title' => 'Kalėdų pūga']],

            ['matchable', [
                'isbn' => self::ISBN['matchable'],
                'author' => self::AUTHOR,
                '_canonical_match' => true,
            ]],

            ['drift', [
                'isbn' => self::ISBN['drift_shop'],
                '_canonical_isbn' => self::ISBN['drift_canonical'],
            ]],
        ];
    }

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

    public static function build(Connection $db): array
    {
        self::guard($db);

        $shopId = $db->transaction(function () use ($db): int {
            self::clear($db);
            self::assertNoIsbnCollision($db);

            return (int) $db->selectOne(
                'insert into shops (name, base_url) values (?, ?) '
                .'on conflict (name) do update set base_url = excluded.base_url '
                .'returning id',
                [self::SHOP, self::BASE]
            )->id;
        });

        $cases = self::cases();

        $db->transaction(function () use ($db, $shopId, $cases): void {
            foreach ($cases as [$slug, $overrides]) {
                self::insertCase($db, $shopId, $slug, $overrides);
            }
            $runId = self::insertRunFixtures($db, $shopId);
            self::insertHistoryFixtures($db, $shopId, $runId);
            self::insertSecondShop($db);
        });

        return ['shop_id' => $shopId, 'rows' => count($cases)];
    }

    private static function insertRunFixtures(Connection $db, int $shopId): int
    {
        $runId = (int) $db->selectOne(
            'insert into scrape_runs (shop_id, phase, status, started_at, finished_at, '
            .'urls_total, urls_processed, items_added, items_updated, errors_4xx, '
            .'errors_5xx, error_count, last_heartbeat, pid, resumable_after_failure, '
            ."close_reason) values (?, 'scan', 'completed', now() - make_interval(mins => 30), "
            .'now() - make_interval(mins => 5), 26, 26, 20, 6, 1, 1, 2, '
            ."now() - make_interval(mins => 5), 4242, false, 'finished') returning id",
            [$shopId]
        )->id;

        $urls = $db->select(
            'select id, url from discovered_urls where shop_id = ? order by id limit 3',
            [$shopId]
        );

        $states = [
            ['done', 200, 12_345],
            ['failed', 500, 0],
            ['pending', null, null],
        ];
        foreach ($urls as $i => $url) {
            [$status, $httpStatus, $bytes] = $states[$i] ?? $states[0];
            $db->statement(
                'insert into scrape_url_items (run_id, shop_id, discovered_url_id, url, '
                .'status, created_at, claimed_at, done_at, url_type, http_status, '
                .'request_delay_s, delay_source, retry_count, response_bytes, attempts) '
                .'values (?, ?, ?, ?, ?, now() - make_interval(mins => 30), '
                .'now() - make_interval(mins => 29), now() - make_interval(mins => 28), '
                ."'product', ?, 0.5, 'shop_settings', 0, ?, 1)",
                [$runId, $shopId, $url->id, $url->url, $status, $httpStatus, $bytes]
            );
        }

        $db->statement(
            'insert into cron_jobs (shop_id, phase, strategy, args, cron_expression, '
            ."enabled, last_run_at, created_at) values (?, 'discover', 'sitemap', '', "
            ."'0 3 * * *', true, now() - make_interval(days => 1), now())",
            [$shopId]
        );

        $book = $db->selectOne(
            'select id, url from shop_books where shop_id = ? order by id limit 1',
            [$shopId]
        );
        $db->statement(
            'insert into validation_issues (last_seen_run_id, url, field, issue, raw_value, '
            .'shop_book_id, lifecycle_state, shop_id, first_seen_run_id, run_count) '
            ."values (?, ?, 'format', 'format_is_dimensions', '17x24', ?, 'new', ?, ?, 1)",
            [$runId, $book->url, $book->id, $shopId, $runId]
        );

        return $runId;
    }

    private static function insertCanonical(Connection $db, string $title, string $slug): int
    {
        $publisher = $db->selectOne(
            'select id from publishers where name = ?',
            ['Synthetic Press']
        );
        $publisherId = $publisher !== null ? (int) $publisher->id : (int) $db->selectOne(
            'insert into publishers (name, created_at) values (?, now()) returning id',
            ['Synthetic Press']
        )->id;

        $canonical = (int) $db->selectOne(
            'insert into books (data_source, title, year, publisher_id, type, format, '
            .'language, upcoming_release, created_at, updated_at, source_url) values '
            ."('shop_inferred', ?, 2024, ?, 'book', 'paperback', 'lt', false, now(), "
            .'now(), ?) returning id',
            [$title, $publisherId, self::BASE.'/canonical/'.$slug]
        )->id;

        $db->statement(
            'insert into book_authors (book_id, author_id, role, position) '
            ."values (?, ?, 'author', 0)",
            [$canonical, self::authorId($db)]
        );

        return $canonical;
    }

    private static function authorId(Connection $db): int
    {
        $found = $db->selectOne('select id from authors where name = ?', [self::AUTHOR]);

        return $found !== null ? (int) $found->id : (int) $db->selectOne(
            'insert into authors (name, normalized_name, created_at) '
            .'values (?, ?, now()) returning id',
            [self::AUTHOR, mb_strtolower(self::AUTHOR)]
        )->id;
    }

    private static function insertHistoryFixtures(Connection $db, int $shopId, int $runId): void
    {
        $book = $db->selectOne(
            'select id, url, price from shop_books where shop_id = ? and price is not null '
            .'order by id limit 1',
            [$shopId]
        );

        $db->statement(
            'insert into prices (shop_book_id, price, in_stock, scraped_at) '
            .'values (?, ?, true, now() - make_interval(days => 3))',
            [$book->id, '7.49']
        );
        $db->statement(
            'insert into shop_book_changes (shop_book_id, scrape_run_id, field, '
            .'old_value, new_value, changed_at) values (?, ?, ?, ?, ?, now())',
            [$book->id, $runId, 'price', '7.49', (string) $book->price]
        );

        $db->statement(
            'insert into scrape_run_events (run_id, event_type, actor, payload, created_at) '
            ."values (?, 'started', 'fixture', ?::jsonb, now() - make_interval(mins => 30))",
            [$runId, '{"note": "fixture run started"}']
        );

        $item = $db->selectOne(
            'select id, url, discovered_url_id from scrape_url_items '
            ."where run_id = ? and status = 'failed' order by id limit 1",
            [$runId]
        );
        $db->statement(
            'insert into scrape_failures (scrape_url_item_id, run_id, shop_id, url, '
            .'occurred_at, error_reason, http_status, lifecycle_state) values '
            ."(?, ?, ?, ?, now(), 'http_404', 404, 'new')",
            [$item->id, $runId, $shopId, $item->url]
        );
        $db->statement(
            'update discovered_urls set fail_count = 3, last_http_status = 404, '
            .'last_checked_at = now() where id = ?',
            [$item->discovered_url_id]
        );

        for ($i = 3; $i >= 1; $i--) {
            $failed = (int) $db->selectOne(
                'insert into scrape_runs (shop_id, phase, status, started_at, finished_at, '
                .'urls_total, urls_processed, items_added, items_updated, errors_4xx, '
                .'errors_5xx, error_count, last_heartbeat, resumable_after_failure, '
                ."close_reason) values (?, 'discover_categories', 'failed', "
                .'now() - make_interval(days => ?), now() - make_interval(days => ?), '
                ."1, 0, 0, 0, 1, 0, 1, now() - make_interval(days => ?), true, 'http_403') "
                .'returning id',
                [$shopId, $i, $i, $i]
            )->id;

            $blocked = self::BASE.'/blocked-category-'.$i;
            $failedItem = (int) $db->selectOne(
                'insert into scrape_url_items (run_id, shop_id, url, status, created_at, '
                .'done_at, url_type, http_status, retry_count, attempts) values '
                ."(?, ?, ?, 'failed', now(), now(), 'category', 403, 0, 1) returning id",
                [$failed, $shopId, $blocked]
            )->id;
            $db->statement(
                'insert into scrape_failures (scrape_url_item_id, run_id, shop_id, url, '
                .'occurred_at, error_reason, http_status, lifecycle_state) values '
                ."(?, ?, ?, ?, now(), 'http_403', 403, 'new')",
                [$failedItem, $failed, $shopId, $blocked]
            );

            $db->statement(
                'insert into validation_issues (last_seen_run_id, url, field, issue, '
                .'raw_value, lifecycle_state, shop_id, first_seen_run_id, run_count) '
                ."values (?, ?, 'run', 'scrape_run_failed', 'http_403', 'new', ?, ?, 1)",
                [$failed, $blocked, $shopId, $failed]
            );
        }

        foreach ([
            ['isbn_duplicate', 'isbn', 'warning-severity issue'],
            ['price_zero', 'price', 'critical-severity issue'],
        ] as [$issue, $field, $raw]) {
            $db->statement(
                'insert into validation_issues (last_seen_run_id, url, field, issue, '
                .'raw_value, shop_book_id, lifecycle_state, shop_id, first_seen_run_id, '
                ."run_count) values (?, ?, ?, ?, ?, ?, 'new', ?, ?, 1)",
                [$runId, $book->url, $field, $issue, $raw, $book->id, $shopId, $runId]
            );
        }
    }

    private static function insertSecondShop(Connection $db): void
    {
        $shopId = (int) $db->selectOne(
            'insert into shops (name, base_url) values (?, ?) '
            .'on conflict (name) do update set base_url = excluded.base_url returning id',
            [self::SHOP_TWO, 'https://synthetic-two.test']
        )->id;

        $canonical = (int) $db->selectOne(
            'select book_id from shop_books where book_id is not null order by id limit 1'
        )->book_id;

        $url = 'https://synthetic-two.test/same-book-different-metadata';
        $bookId = (int) $db->selectOne(
            'insert into shop_books (shop_id, url, title, author, publisher, year, format, '
            .'type, price, in_stock, is_active, categories, match_status, book_id, '
            ."first_seen_at, last_seen_at) values (?, ?, ?, ?, ?, 2019, 'hardcover', "
            ."'book', '11.49', true, true, ?, 'matched', ?, now(), now()) returning id",
            [
                $shopId, $url, 'Same Book, Different Title', self::AUTHOR,
                'Another Press', self::pgArray(['Grožinė literatūra']), $canonical,
            ]
        )->id;
        self::insertUrl($db, $shopId, $url, 'product', $bookId);
        $db->statement(
            'insert into prices (shop_book_id, price, in_stock, scraped_at) '
            ."values (?, '11.49', true, now())",
            [$bookId]
        );
    }

    private static function clear(Connection $db): void
    {

        $db->statement('delete from validation_issues');

        foreach (['prices', 'shop_book_attributes', 'shop_book_authors', 'shop_book_changes'] as $table) {
            $db->statement(
                "delete from {$table} where shop_book_id in (select sb.id from shop_books sb "
                .'join shops s on s.id = sb.shop_id where s.name in (?, ?))',
                [self::SHOP, self::SHOP_TWO]
            );
        }
        $db->statement(
            'delete from scrape_failures where shop_id in '
            .'(select id from shops where name in (?, ?))',
            [self::SHOP, self::SHOP_TWO]
        );
        $db->statement(
            'delete from scrape_url_items where shop_id in '
            .'(select id from shops where name in (?, ?))',
            [self::SHOP, self::SHOP_TWO]
        );
        $db->statement(
            'delete from scrape_run_events where run_id in '
            .'(select id from scrape_runs where shop_id in '
            .'(select id from shops where name in (?, ?)))',
            [self::SHOP, self::SHOP_TWO]
        );
        $db->statement(
            'delete from cron_jobs where shop_id in (select id from shops where name in (?, ?))',
            [self::SHOP, self::SHOP_TWO]
        );

        foreach ([
            'update shop_books set created_run_id = null',
            'update discovered_urls set last_seen_run_id = null',
        ] as $statement) {
            $db->statement(
                $statement.' where shop_id in (select id from shops where name in (?, ?))',
                [self::SHOP, self::SHOP_TWO]
            );
        }
        $db->statement(
            'delete from scrape_runs where shop_id in (select id from shops where name in (?, ?))',
            [self::SHOP, self::SHOP_TWO]
        );
        $db->statement(
            'delete from discovered_urls where shop_id in (select id from shops where name in (?, ?))',
            [self::SHOP, self::SHOP_TWO]
        );
        $db->statement(
            'delete from shop_books where shop_id in (select id from shops where name in (?, ?))',
            [self::SHOP, self::SHOP_TWO]
        );

        $db->statement(
            'delete from book_isbns where book_id in (select id from books where source_url like ?)',
            [self::BASE.'/%']
        );
        $db->statement(
            'delete from book_authors where book_id in '
            .'(select id from books where source_url like ?)',
            [self::BASE.'/%']
        );
        $db->statement('delete from books where source_url like ?', [self::BASE.'/%']);
        $db->statement('delete from shop_authors where name = ?', [self::AUTHOR]);
        $db->statement('delete from authors where name = ?', [self::AUTHOR]);
    }

    private static function assertNoIsbnCollision(Connection $db): void
    {
        $clash = $db->select(
            'select isbn from book_isbns where isbn in ('
            .implode(',', array_fill(0, count(self::ISBN), '?')).')',
            array_values(self::ISBN)
        );
        if ($clash !== []) {
            throw new RuntimeException(sprintf(
                'refusing to build: %s already exist(s) in book_isbns. The fixture '
                .'ISBNs must belong to nothing else, or the matcher links these '
                .'books to a canonical the fixture does not control.',
                implode(', ', array_map(static fn ($r) => $r->isbn, $clash))
            ));
        }
    }

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
        $url = self::BASE.'/'.$slug;

        $bookId = (int) $db->selectOne(
            'insert into shop_books (shop_id, url, title, author, isbn, sku, publisher, '
            .'year, format, type, price, in_stock, is_active, categories, match_status, '
            .'first_seen_at, last_seen_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '
            ."'unmatched', now(), coalesce(?::timestamptz, now())) returning id",
            [
                $shopId, $url, $row['title'], $row['author'], $row['isbn'], $row['sku'],
                $row['publisher'], $row['year'], $row['format'], $row['type'], $row['price'],
                $row['in_stock'], $row['is_active'], self::pgArray($row['categories']),
                $overrides['_last_seen_at'] ?? null,
            ]
        )->id;

        if (isset($overrides['_canonical_isbn'])) {
            $canonical = self::insertCanonical($db, $row['title'], $slug);
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
            $canonical = self::insertCanonical($db, $row['title'], $slug);
            $db->statement(
                "insert into book_isbns (book_id, isbn, isbn_type) values (?, ?, 'isbn13')",
                [$canonical, $row['isbn']]
            );

            $shopAuthor = (int) $db->selectOne(
                'insert into shop_authors (name, normalized_name, created_at) '
                .'values (?, ?, now()) returning id',
                [self::AUTHOR, mb_strtolower(self::AUTHOR)]
            )->id;
            $db->statement(
                'insert into shop_book_authors (shop_book_id, author_id, position) '
                .'values (?, ?, 0)',
                [$bookId, $shopAuthor]
            );
        }

        if ($overrides['_no_url'] ?? false) {
            return;
        }

        self::insertUrl($db, $shopId, $url, $overrides['_url_type'] ?? 'product', $bookId);
        foreach ($overrides['_extra_urls'] ?? [] as [$urlType, $altSlug]) {
            self::insertUrl($db, $shopId, self::BASE.'/'.$altSlug, $urlType, $bookId);
        }

        if ($overrides['_no_price'] ?? false) {
            return;
        }
        $db->statement(
            'insert into prices (shop_book_id, price, in_stock, scraped_at) '
            .'values (?, ?, ?, now())',
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
            ."fail_count, first_seen_at, last_seen_at, shop_book_id) values (?, ?, ?, 'sitemap', "
            .'?, 0, now(), now(), ?)',
            [$shopId, $url, $url, $urlType, $bookId]
        );
    }

    private static function pgArray(array $values): string
    {
        return '{'.implode(',', array_map(
            static fn (string $v): string => '"'.str_replace(['\\', '"'], ['\\\\', '\"'], $v).'"',
            $values
        )).'}';
    }

    private static function guard(Connection $db): void
    {
        $port = (int) ($db->getConfig('port') ?? 0);
        $name = (string) ($db->getConfig('database') ?? '');

        if ($port !== self::TEST_PORT) {
            throw new RuntimeException(sprintf(
                'refusing to build: %s is on port %d, not the test cluster (%d). '
                .'The real catalogue is on 5432.',
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
