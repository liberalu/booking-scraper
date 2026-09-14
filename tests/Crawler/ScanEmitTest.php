<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Crawler\CrawlerContext;
use App\Crawler\IssueBuffer;
use App\Crawler\ScanSpider;
use PHPUnit\Framework\TestCase;
use RoachPHP\Http\Request;
use RoachPHP\Http\Response;
use RoachPHP\ItemPipeline\ItemInterface;

final class ScanEmitTest extends TestCase
{
    public function test_a_page_without_a_title_that_the_parser_rejects_is_a_non_product_not_silence(): void
    {
        $items = $this->parse('pegasas', 'https://www.pegasas.lt', 'https://www.pegasas.lt/some-book-123', '<html><body>PWA shell</body></html>');

        self::assertCount(1, $items);
        self::assertSame('non_product', $items[0]['kind']);
        self::assertSame('https://www.pegasas.lt/some-book-123', $items[0]['url']);
        self::assertSame([['key' => 'pwa_shell_no_data', 'points' => 0]], $items[0]['book_score_reasons']);
    }

    public function test_a_titled_page_the_classifier_rejects_is_a_non_product(): void
    {
        $body = (string) file_get_contents(__DIR__.'/../fixtures/humanitas/product_without_book_info.html');
        $items = $this->parse('humanitas', 'https://www.humanitas.lt', 'https://www.humanitas.lt/produktas/x', $body);

        self::assertCount(1, $items);
        self::assertSame('non_product', $items[0]['kind']);
        self::assertNotEmpty($items[0]['book_score_reasons']);
    }

    public function test_a_book_page_is_a_book(): void
    {
        $body = (string) file_get_contents(__DIR__.'/../fixtures/vaga_product_page.html');
        $items = $this->parse('vaga', 'https://vaga.lt', 'https://vaga.lt/a-book', $body);

        self::assertCount(1, $items);
        self::assertSame('book', $items[0]['kind']);
        self::assertNotEmpty($items[0]['parsed']['title']);
    }

    /** @return list<array<string, mixed>> */
    private function parse(string $shop, string $baseUrl, string $url, string $body): array
    {
        $spider = new ScanSpider(new CrawlerContext(new IssueBuffer));
        $spider->withContext(['shop' => $shop, 'base_url' => $baseUrl, 'urls' => [$url]]);

        $request = new Request('GET', $url, $spider->parse(...));
        $response = new Response(new \Nyholm\Psr7\Response(200, [], $body), $request);

        $items = [];
        foreach ($spider->parse($response) as $result) {
            $value = $result->value();
            if ($value instanceof ItemInterface) {
                $items[] = $value->all();
            }
        }

        return $items;
    }
}
