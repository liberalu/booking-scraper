<?php

declare(strict_types=1);

namespace BookScraper\Tests;

use BookScraper\Database;
use BookScraper\Models\Shop;
use BookScraper\Services\ValidateService;
use Illuminate\Database\Capsule\Manager as Capsule;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

/**
 * Mirrors the all-inactive-shop guard in
 * tests/integration/test_validate_service.py.
 *
 * A grep can prove the gate literal appears once; only running the checks
 * against a fully-delisted shop proves a NEW check remembered to use the
 * factory at all. Seven checks had drifted this way.
 */
final class ValidateServiceGatesTest extends TestCase
{
    private static ?Capsule $capsule = null;

    private int $shopId;

    protected function setUp(): void
    {
        self::$capsule ??= Database::boot(
            getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_test'
        );
        DB::beginTransaction();

        $this->shopId = Shop::firstOrCreate(
            ['name' => 'gates-test'],
            ['base_url' => 'https://gates.test']
        )->id;
    }

    protected function tearDown(): void
    {
        DB::rollBack();
    }

    public function test_no_check_fires_on_a_fully_delisted_shop(): void
    {
        // Every row here is problem-shaped: duplicate ISBN, no price, no
        // metadata, a dimension format, a bad year, a slug that shares nothing
        // with the title. All delisted, so none of it is a data-quality issue
        // — the catalogue no longer contains them.
        //
        // Deliberately NOT a duplicate SKU: `uq_shop_books_shop_sku` is a
        // unique index on (shop_id, sku), so that state cannot exist. An
        // earlier version of this fixture inserted the pair anyway and only
        // passed because the test database's schema had drifted from the
        // migrations. Both are fixed now: the dead sku_duplicate check is
        // gone, and the index is declared on the model the test schema is
        // built from.
        foreach ([1, 2] as $n) {
            $id = DB::table('shop_books')->insertGetId([
                'shop_id' => $this->shopId,
                'url' => "https://gates.test/completely-different-slug-{$n}",
                'title' => 'Nothing In Common Here',
                'author' => null,
                'isbn' => '9786090901595',
                'sku' => "GATES-SKU-{$n}",
                'year' => 1200,
                'format' => '17x24',
                'type' => 'book',
                'price' => null,
                'in_stock' => true,
                'is_active' => false,
                'match_status' => 'unmatched',
                'first_seen_at' => Carbon::now('UTC')->subYears(2),
                'last_seen_at' => Carbon::now('UTC')->subYears(2),
            ], 'id');

            DB::table('discovered_urls')->insert([
                'shop_id' => $this->shopId,
                'url' => "https://gates.test/alias-{$n}",
                'normalized_url' => "https://gates.test/alias-{$n}",
                'source' => 'sitemap',
                'url_type' => 'unreachable',
                'fail_count' => 5,
                'first_seen_at' => Carbon::now('UTC'),
                'last_seen_at' => Carbon::now('UTC'),
                'shop_book_id' => $id,
            ]);
        }

        $runId = DB::table('scrape_runs')->insertGetId([
            'shop_id' => $this->shopId,
            'phase' => 'validate',
            'status' => 'running',
            'started_at' => Carbon::now('UTC'),
            'urls_processed' => 0,
            'items_added' => 0,
            'items_updated' => 0,
            'errors_4xx' => 0,
            'errors_5xx' => 0,
            'error_count' => 0,
        ], 'id');

        $counters = (new ValidateService())->run($this->shopId, $runId);

        self::assertSame(
            [],
            $counters,
            'a delisted row is not a data-quality problem — some check is missing its gate'
        );
    }

    public function test_an_active_version_of_the_same_row_does_fire(): void
    {
        // Control: the fixture above is genuinely problem-shaped, so the
        // previous test passing because of a typo'd query would show up here.
        $id = DB::table('shop_books')->insertGetId([
            'shop_id' => $this->shopId,
            'url' => 'https://gates.test/completely-different-slug',
            'title' => 'Nothing In Common Here',
            'isbn' => '9786090901595',
            'year' => 1200,
            'format' => '17x24',
            'type' => 'book',
            'price' => null,
            'in_stock' => true,
            'is_active' => true,
            'match_status' => 'unmatched',
            'first_seen_at' => Carbon::now('UTC'),
            'last_seen_at' => Carbon::now('UTC'),
        ], 'id');

        $runId = DB::table('scrape_runs')->insertGetId([
            'shop_id' => $this->shopId,
            'phase' => 'validate',
            'status' => 'running',
            'started_at' => Carbon::now('UTC'),
            'urls_processed' => 0,
            'items_added' => 0,
            'items_updated' => 0,
            'errors_4xx' => 0,
            'errors_5xx' => 0,
            'error_count' => 0,
        ], 'id');

        $counters = (new ValidateService())->run($this->shopId, $runId);

        self::assertArrayHasKey('year_out_of_range', $counters);
        self::assertArrayHasKey('format_is_dimensions', $counters);
        self::assertArrayHasKey('slug_title_mismatch', $counters);
        self::assertArrayHasKey('active_no_price', $counters);
        self::assertSame($id, (int) DB::table('validation_issues')
            ->where('issue', 'year_out_of_range')->value('shop_book_id'));
    }
}
