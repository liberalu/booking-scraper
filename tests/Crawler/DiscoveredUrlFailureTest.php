<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Repositories\DiscoveredUrlRepository;
use App\Support\Database;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;

final class DiscoveredUrlFailureTest extends TestCase
{
    private static bool $booted = false;

    private int $shopId;

    private DiscoveredUrlRepository $urls;

    protected function setUp(): void
    {
        if (! self::$booted) {
            Database::boot(getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');
            self::$booted = true;
        }
        DB::beginTransaction();
        $this->urls = new DiscoveredUrlRepository;
        $this->shopId = DB::table('shops')->insertGetId(['name' => 'fail-count-test', 'base_url' => 'https://fail.test'], 'id');
    }

    protected function tearDown(): void
    {
        DB::rollBack();
    }

    private function plant(string $url, string $type, ?int $shopBookId = null): int
    {
        return DB::table('discovered_urls')->insertGetId([
            'shop_id' => $this->shopId,
            'url' => $url,
            'normalized_url' => $url,
            'url_type' => $type,
            'source' => 'sitemap',
            'fail_count' => 0,
            'shop_book_id' => $shopBookId,
            'first_seen_at' => Date::now('UTC'),
            'last_seen_at' => Date::now('UTC'),
        ], 'id');
    }

    private function plantBook(string $url): int
    {
        return DB::table('shop_books')->insertGetId([
            'shop_id' => $this->shopId,
            'url' => $url,
            'title' => 'A book',
            'type' => 'book',
            'match_status' => 'unmatched',
            'is_active' => true,
            'in_stock' => true,
            'first_seen_at' => Date::now('UTC'),
            'last_seen_at' => Date::now('UTC'),
        ], 'id');
    }

    public function test_the_third_failure_retires_the_url_and_deactivates_its_book(): void
    {
        $url = 'https://fail.test/gone';
        $bookId = $this->plantBook($url);
        $this->plant($url, 'product', $bookId);

        $this->urls->recordFetchFailure($this->shopId, $url, 404);
        $this->urls->recordFetchFailure($this->shopId, $url, 404);
        $row = DB::table('discovered_urls')->where('url', $url)->first();
        self::assertSame(2, $row->fail_count);
        self::assertSame('product', $row->url_type, 'two failures are not yet a verdict');
        self::assertSame(404, $row->last_http_status);

        $this->urls->recordFetchFailure($this->shopId, $url, 404);
        $row = DB::table('discovered_urls')->where('url', $url)->first();
        self::assertSame(3, $row->fail_count);
        self::assertSame('unreachable', $row->url_type);
        self::assertFalse((bool) DB::table('shop_books')->where('id', $bookId)->value('is_active'));
        self::assertNotNull(DB::table('shop_books')->where('id', $bookId)->value('inactive_since'));
    }

    public function test_a_non_product_is_never_promoted_to_unreachable(): void
    {
        $url = 'https://fail.test/category';
        $this->plant($url, 'non_product');

        foreach (range(1, 4) as $_) {
            $this->urls->recordFetchFailure($this->shopId, $url, 500);
        }

        self::assertSame('non_product', DB::table('discovered_urls')->where('url', $url)->value('url_type'));
    }

    public function test_a_successful_scrape_clears_the_failure_streak(): void
    {
        $url = 'https://fail.test/back';
        $bookId = $this->plantBook($url);
        $this->plant($url, 'product', $bookId);
        foreach (range(1, 3) as $_) {
            $this->urls->recordFetchFailure($this->shopId, $url, 503);
        }
        self::assertSame('unreachable', DB::table('discovered_urls')->where('url', $url)->value('url_type'));

        $this->urls->linkToShopBook($this->shopId, $url, $bookId);

        $row = DB::table('discovered_urls')->where('url', $url)->first();
        self::assertSame(0, $row->fail_count);
        self::assertSame('product', $row->url_type);
        self::assertSame(200, $row->last_http_status);
    }

    public function test_an_unknown_url_is_ignored(): void
    {
        self::assertNull($this->urls->recordFetchFailure($this->shopId, 'https://fail.test/never-seen', 404));
    }
}
