<?php

declare(strict_types=1);

namespace BookScraper\Crawler\Tests;

use BookScraper\Crawler\DiscoverSpider;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;
use ReflectionClass;
use RoachPHP\Http\Request;
use RoachPHP\Http\Response;
use RoachPHP\ItemPipeline\ItemInterface;
use RoachPHP\Spider\ParseResult;

/**
 * The emit rules decide what discovery writes, and each gate exists for a
 * reason recorded in the Python spider. Exercised offline against the
 * shared fixture — no network.
 */
final class DiscoverEmitTest extends TestCase
{
    private function spider(array $context = []): DiscoverSpider
    {
        $spider = new DiscoverSpider();
        $spider->withContext($context + [
            'shop' => 'vaga',
            'strategy' => 'categories',
            'base_url' => 'https://vaga.lt',
            'url_template' => 'https://vaga.lt/knygos?limit=100&page={page}',
            'page_size' => 100,
        ]);

        return $spider;
    }

    /** @return list<array<string, mixed>> emitted items, in order */
    private function emit(DiscoverSpider $spider, array $products): array
    {
        $method = (new ReflectionClass($spider))->getMethod('emitProducts');
        $method->setAccessible(true);

        $out = [];
        foreach ($method->invoke($spider, $products) as $result) {
            /** @var ParseResult $result */
            $value = $result->value();
            if ($value instanceof ItemInterface) {
                $out[] = $value->all();
            }
        }

        return $out;
    }

    public function test_a_full_listing_row_emits_a_url_and_a_book(): void
    {
        $items = $this->emit($this->spider(), [[
            'url' => 'https://vaga.lt/a-book',
            'title' => 'A Book',
            'author' => 'An Author',
            'price' => '12.34',
        ]]);

        self::assertCount(2, $items);
        self::assertSame('url', $items[0]['kind']);
        self::assertSame('category', $items[0]['source']);
        self::assertSame('book', $items[1]['kind']);
        self::assertSame('A Book', $items[1]['parsed']['title']);
        self::assertSame('12.34', $items[1]['parsed']['price']);
    }

    public function test_relative_urls_are_absolutised_against_base_url(): void
    {
        $items = $this->emit($this->spider(), [[
            'url' => '/relative-book',
            'title' => 'T',
            'price' => '1.00',
        ]]);

        self::assertSame('https://vaga.lt/relative-book', $items[0]['url']);
    }

    #[DataProvider('incompleteListings')]
    public function test_incomplete_rows_still_record_the_url_but_no_book(array $product): void
    {
        // The URL must always be tracked: the scan spider fetches the full
        // page and sets url_type authoritatively. Only the book row is held
        // back, so a stub never lands in shop_books.
        $items = $this->emit($this->spider(), [$product]);

        self::assertCount(1, $items);
        self::assertSame('url', $items[0]['kind']);
    }

    /** @return array<string, array{0: array<string, mixed>}> */
    public static function incompleteListings(): array
    {
        return [
            'no price' => [['url' => 'https://vaga.lt/x', 'title' => 'T', 'price' => null]],
            'no title' => [['url' => 'https://vaga.lt/x', 'title' => null, 'price' => '1.00']],
            'price missing entirely' => [['url' => 'https://vaga.lt/x', 'title' => 'T']],
        ];
    }

    public function test_known_non_book_records_the_url_but_never_a_book_row(): void
    {
        // Writing a non_book row during discover produces url_type='product'
        // / type='non_book' mismatches (product_url_non_book) that persist
        // until the next scan corrects them.
        $items = $this->emit($this->spider(), [[
            'url' => 'https://vaga.lt/board-game',
            'title' => 'Stalo žaidimas',
            'price' => '25.00',
            'is_book_product' => false,
        ]]);

        self::assertCount(1, $items);
        self::assertSame('url', $items[0]['kind']);
    }

    public function test_rows_without_a_url_are_skipped_entirely(): void
    {
        self::assertSame([], $this->emit($this->spider(), [
            ['title' => 'No URL', 'price' => '1.00'],
            ['url' => '', 'title' => 'Empty URL', 'price' => '1.00'],
        ]));
    }

    public function test_listing_defaults_in_stock_true(): void
    {
        $items = $this->emit($this->spider(), [[
            'url' => 'https://vaga.lt/x', 'title' => 'T', 'price' => '1.00',
        ]]);

        self::assertTrue($items[1]['parsed']['in_stock']);
    }

    // --------------------------------------------------------- pagination

    public function test_page_one_enqueues_every_remaining_page_upfront(): void
    {
        // Chaining page+1 serialises discovery no matter the concurrency;
        // upfront enqueueing is what lets concurrency engage.
        $pages = $this->enqueuedPages(total: 350, maxPages: 0);

        self::assertSame([2, 3, 4], $pages, 'ceil(350/100) = 4 pages');
    }

    public function test_max_pages_caps_the_upfront_enqueue(): void
    {
        self::assertSame([2, 3], $this->enqueuedPages(total: 9910, maxPages: 3));
    }

    public function test_a_single_page_total_enqueues_nothing(): void
    {
        self::assertSame([], $this->enqueuedPages(total: 40, maxPages: 0));
    }

    /** @return list<int> page numbers of the follow-up requests */
    private function enqueuedPages(int $total, int $maxPages): array
    {
        $spider = $this->spider(['max_pages' => $maxPages]);
        $method = (new ReflectionClass($spider))->getMethod('enqueueRemainingPages');
        $method->setAccessible(true);

        $pages = [];
        foreach ($method->invoke($spider, $total) as $result) {
            /** @var ParseResult $result */
            $value = $result->value();
            if ($value instanceof Request) {
                parse_str((string) parse_url($value->getUri(), PHP_URL_QUERY), $query);
                $pages[] = (int) ($query['page'] ?? 0);
            }
        }

        return $pages;
    }

    // ------------------------------------------------------------- sitemap

    public function test_sitemap_emits_each_unique_url_once(): void
    {
        $xml = (string) file_get_contents(__DIR__ . '/../../../fixtures/vaga_sitemap.xml');
        $spider = $this->spider(['strategy' => 'sitemap']);

        $request = new Request('GET', 'https://vaga.lt/sitemap.xml', [$spider, 'parse']);
        $response = new Response(new \Nyholm\Psr7\Response(200, [], $xml), $request);

        $urls = [];
        foreach ($spider->parseSitemap($response) as $result) {
            $value = $result->value();
            if ($value instanceof ItemInterface) {
                $urls[] = $value->get('url');
                self::assertSame('sitemap', $value->get('source'));
            }
        }

        self::assertSame($urls, array_values(array_unique($urls)), 'no duplicates emitted');
        self::assertNotEmpty($urls);
    }
}
