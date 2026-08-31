<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Crawler\ItemBuilder;
use App\Crawler\Persister;
use App\Models\DiscoveredUrl;
use App\Models\Price;
use App\Models\Shop;
use App\Models\ShopBookAttribute;
use App\Parsers\Vaga\Parser;
use App\Repositories\CrawlerPersistenceRepository;
use App\Support\Database;
use Illuminate\Database\Capsule\Manager as Capsule;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\TestCase;
use RuntimeException;

final class PersisterTest extends TestCase
{
    private static ?Capsule $capsule = null;

    private Persister $persister;

    private int $shopId;

    protected function setUp(): void
    {
        self::$capsule ??= Database::boot(
            getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test'
        );
        DB::beginTransaction();

        $this->persister = new Persister;

        $this->shopId = Shop::firstOrCreate(
            ['name' => 'persister-test'],
            ['base_url' => 'https://persister.test']
        )->id;
    }

    protected function tearDown(): void
    {
        DB::rollBack();
    }

    private function fixture(): array
    {
        return Parser::parseProductPage(
            (string) file_get_contents(__DIR__.'/../fixtures/vaga_product_page.html')
        );
    }

    public function test_persists_the_fixture_product_end_to_end(): void
    {
        $url = 'https://persister.test/sirdies-kauleliai';
        ['result' => $result] = $this->persister->persist($this->shopId, $url, $this->fixture());

        $book = $result->shopBook;
        self::assertTrue($result->created);
        self::assertSame('Širdies kauleliai', $book->title);
        self::assertSame('Colleen Hoover', $book->author);
        self::assertSame('9786090901595', $book->isbn);
        self::assertSame('1005584', $book->sku);
        self::assertSame('Baltos lankos', $book->publisher);
        self::assertSame(2025, $book->year);
        self::assertSame('paperback', $book->format);
        self::assertSame('book', $book->type);
        self::assertTrue($book->in_stock);
        self::assertSame('16.32', (string) $book->price);
        self::assertSame('24.39', (string) $book->price_original);
        self::assertSame(
            ['Meilės romanai', 'Jausmų romanai', 'Širdies kauleliai'],
            $book->categories
        );
    }

    public function test_writes_the_page_properties_as_attributes(): void
    {
        ['result' => $result] = $this->persister->persist(
            $this->shopId,
            'https://persister.test/sirdies-kauleliai',
            $this->fixture()
        );

        $attrs = ShopBookAttribute::where('shop_book_id', $result->shopBook->id)
            ->pluck('value', 'key')
            ->all();

        self::assertSame('336', $attrs['pages']);
        self::assertSame('Minkštas', $attrs['cover_type']);
    }

    public function test_appends_a_price_row_on_every_scrape(): void
    {
        $url = 'https://persister.test/sirdies-kauleliai';
        $parsed = $this->fixture();

        ['result' => $first] = $this->persister->persist($this->shopId, $url, $parsed);
        $this->persister->persist($this->shopId, $url, $parsed);
        $this->persister->persist($this->shopId, $url, $parsed);

        self::assertSame(
            3,
            Price::where('shop_book_id', $first->shopBook->id)->count()
        );
    }

    public function test_no_price_row_when_the_page_has_no_price(): void
    {
        $parsed = $this->fixture();
        $parsed['price'] = null;

        ['result' => $result, 'price_written' => $written] = $this->persister->persist(
            $this->shopId,
            'https://persister.test/no-price',
            $parsed
        );

        self::assertFalse($written);
        self::assertSame(0, Price::where('shop_book_id', $result->shopBook->id)->count());
    }

    public function test_links_the_url_row_and_marks_it_product(): void
    {
        $url = 'https://persister.test/sirdies-kauleliai';
        ['result' => $result] = $this->persister->persist($this->shopId, $url, $this->fixture());

        $row = DiscoveredUrl::where('shop_id', $this->shopId)
            ->where('normalized_url', $url)
            ->firstOrFail();

        self::assertSame($result->shopBook->id, $row->shop_book_id);

        self::assertSame('product', $row->url_type);
    }

    public function test_missing_isbn_marks_the_url_partial_so_the_delta_scan_retries(): void
    {
        $parsed = $this->fixture();
        $parsed['isbn'] = null;

        $this->persister->persist($this->shopId, 'https://persister.test/partial', $parsed);

        $row = DiscoveredUrl::where('shop_id', $this->shopId)
            ->where('normalized_url', 'https://persister.test/partial')
            ->firstOrFail();

        self::assertSame('product_partial', $row->url_type);
    }

    public function test_a_complete_rescrape_promotes_partial_to_product(): void
    {
        $url = 'https://persister.test/promote';
        $partial = $this->fixture();
        $partial['isbn'] = null;
        $this->persister->persist($this->shopId, $url, $partial);

        $this->persister->persist($this->shopId, $url, $this->fixture());

        self::assertSame(
            'product',
            DiscoveredUrl::where('shop_id', $this->shopId)
                ->where('normalized_url', $url)->firstOrFail()->url_type
        );
    }

    public function test_a_partial_rescrape_does_not_demote_a_complete_row(): void
    {
        $url = 'https://persister.test/sticky';
        $this->persister->persist($this->shopId, $url, $this->fixture());

        $partial = $this->fixture();
        $partial['isbn'] = null;
        $this->persister->persist($this->shopId, $url, $partial);

        self::assertSame(
            'product',
            DiscoveredUrl::where('shop_id', $this->shopId)
                ->where('normalized_url', $url)->firstOrFail()->url_type
        );
    }

    public function test_records_field_changes(): void
    {
        $url = 'https://persister.test/changes';
        $this->persister->persist($this->shopId, $url, $this->fixture());

        $changed = $this->fixture();
        $changed['title'] = 'Renamed Title';
        $changed['price'] = '19.99';
        ['result' => $result] = $this->persister->persist($this->shopId, $url, $changed);

        $rows = DB::table('shop_book_changes')
            ->where('shop_book_id', $result->shopBook->id)
            ->pluck('new_value', 'field')
            ->all();

        self::assertSame('Renamed Title', $rows['title']);
    }

    public function test_item_builder_keeps_parser_supplied_properties(): void
    {

        $built = ItemBuilder::fromParsed([
            'title' => 'X',
            'properties' => ['language' => 'lietuvių', 'ean' => '123'],
            'pages' => 100,
        ]);

        self::assertSame(
            ['language' => 'lietuvių', 'ean' => '123', 'pages' => 100],
            $built['properties']
        );
    }

    public function test_repository_transaction_rolls_back_every_write_on_failure(): void
    {
        $name = 'rollback-'.bin2hex(random_bytes(6));
        $repository = new CrawlerPersistenceRepository;

        try {
            $repository->transaction(function () use ($name): array {
                Shop::create(['name' => $name, 'base_url' => "https://{$name}.test"]);

                throw new RuntimeException('force rollback');
            });
            self::fail('transaction failure was swallowed');
        } catch (RuntimeException $exception) {
            self::assertSame('force rollback', $exception->getMessage());
        }

        self::assertFalse(Shop::where('name', $name)->exists());
    }
}
