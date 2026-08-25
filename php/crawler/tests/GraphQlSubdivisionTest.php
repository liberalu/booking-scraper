<?php

declare(strict_types=1);

namespace BookScraper\Crawler\Tests;

use BookScraper\Crawler\DiscoverSpider;
use BookScraper\Database;
use BookScraper\Discovery\GraphQlUrls;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;
use RoachPHP\Http\Request;
use RoachPHP\Http\Response;

/**
 * Adaptive subdivision: a 5xx on a GraphQL page is refetched as several
 * smaller pages rather than dropped.
 *
 * Magento's full-page cache misses on deep pages return transient 503s at
 * pageSize=50 under concurrency; the same range at pageSize=10 usually
 * succeeds. The arithmetic is the part worth pinning down — a wrong first
 * sub-page silently skips or re-fetches a slice of the catalogue.
 */
final class GraphQlSubdivisionTest extends TestCase
{
    private const BASE = 'https://www.pegasas.lt';

    private function spider(array $context = []): DiscoverSpider
    {
        $spider = new DiscoverSpider();
        $spider->withContext($context + [
            'shop' => 'pegasas',
            'strategy' => 'graphql',
            'base_url' => self::BASE,
            'category_ids' => ['5107', '5125'],
            'page_size' => 50,
            'subdivide_factor' => 5,
            'subdivide_min_page_size' => 1,
        ]);

        return $spider;
    }

    /**
     * @return list<array{page: int, page_size: int, subdivision_depth: int}>
     */
    private function requestsFor(
        DiscoverSpider $spider,
        int $page,
        int $pageSize,
        int $depth,
        int $status = 503,
    ): array {
        $url = GraphQlUrls::buildPageUrl(self::BASE, ['5107', '5125'], $pageSize, $page, $depth);
        $request = new Request('GET', $url, [$spider, 'parse'], ['page' => $page]);
        $response = new Response(new \Nyholm\Psr7\Response($status, [], ''), $request);

        $out = [];
        foreach ($spider->parseGraphQl($response) as $result) {
            $value = $result->value();
            if ($value instanceof Request) {
                $out[] = GraphQlUrls::parsePageUrl($value->getUri());
            }
        }

        return $out;
    }

    public function test_a_failed_page_is_refetched_as_five_smaller_ones(): void
    {
        $requests = $this->requestsFor($this->spider(), page: 3, pageSize: 50, depth: 0);

        // 5 sub-pages at pageSize=10, then the next normal page.
        self::assertCount(6, $requests);
        self::assertSame(
            [11, 12, 13, 14, 15],
            array_map(static fn (array $r): int => $r['page'], array_slice($requests, 0, 5))
        );
        foreach (array_slice($requests, 0, 5) as $sub) {
            self::assertSame(10, $sub['page_size']);
            self::assertSame(1, $sub['subdivision_depth']);
        }

        // Pagination continues, or one bad page would end the crawl.
        self::assertSame(4, $requests[5]['page']);
        self::assertSame(50, $requests[5]['page_size']);
        self::assertSame(0, $requests[5]['subdivision_depth']);
    }

    /**
     * Page 3 at size 50 covers items 100..149. The sub-pages must cover
     * exactly that range: pages 11..15 at size 10 are items 100..149.
     */
    public function test_the_sub_pages_cover_exactly_the_failed_range(): void
    {
        $requests = $this->requestsFor($this->spider(), page: 3, pageSize: 50, depth: 0);
        $subs = array_slice($requests, 0, 5);

        $first = ($subs[0]['page'] - 1) * $subs[0]['page_size'];
        $last = $subs[4]['page'] * $subs[4]['page_size'];
        self::assertSame(100, $first);
        self::assertSame(150, $last);
    }

    public function test_an_already_subdivided_page_is_not_split_again(): void
    {
        // Recursing here would multiply requests without bound.
        self::assertSame([], $this->requestsFor($this->spider(), page: 12, pageSize: 10, depth: 1));
    }

    public function test_the_max_pages_cap_stops_the_follow_up_page(): void
    {
        $requests = $this->requestsFor(
            $this->spider(['max_pages' => 3]),
            page: 3,
            pageSize: 50,
            depth: 0,
        );

        // Sub-pages still fire — they cover a range already inside the cap —
        // but page 4 does not.
        self::assertCount(5, $requests);
    }

    public function test_a_coarse_factor_still_yields_at_least_two_sub_pages(): void
    {
        $requests = $this->requestsFor(
            $this->spider(['subdivide_factor' => 1]),
            page: 2,
            pageSize: 50,
            depth: 0,
        );

        // factor is floored at 2, so 50 becomes 2 × 25.
        self::assertCount(3, $requests);
        self::assertSame(25, $requests[0]['page_size']);
        self::assertSame([3, 4], [$requests[0]['page'], $requests[1]['page']]);
    }

    public function test_a_2xx_response_is_parsed_rather_than_subdivided(): void
    {
        // An empty body parses to zero products, which ends the branch — the
        // point is that no subdivision requests come out of a 200.
        self::assertSame(
            [],
            $this->requestsFor($this->spider(), page: 3, pageSize: 50, depth: 0, status: 200)
        );
    }

    /**
     * The Timeline card renders these events; without the row an operator
     * sees a quiet run rather than a spider working around a bad backend.
     */
    #[Group('db')]
    public function test_each_subdivision_is_recorded_on_the_run_timeline(): void
    {
        Database::boot(getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_test');
        DB::beginTransaction();
        try {
            $shopId = (int) (DB::table('shops')->where('name', 'subdivide-test')->value('id')
                ?? DB::table('shops')->insertGetId(
                    ['name' => 'subdivide-test', 'base_url' => 'https://subdivide.test'],
                    'id'
                ));
            $runId = (int) DB::table('scrape_runs')->insertGetId([
                'shop_id' => $shopId,
                'phase' => 'discover_graphql',
                'status' => 'running',
                'started_at' => \Illuminate\Support\Carbon::now('UTC'),
                'urls_processed' => 0,
                'items_added' => 0,
                'items_updated' => 0,
                'errors_4xx' => 0,
                'errors_5xx' => 0,
                'error_count' => 0,
            ], 'id');

            $this->requestsFor(
                $this->spider(['run_id' => $runId]),
                page: 3,
                pageSize: 50,
                depth: 0,
            );

            $event = DB::table('scrape_run_events')
                ->where('run_id', $runId)
                ->where('event_type', 'subdivided')
                ->first();
            self::assertNotNull($event);
            $payload = json_decode((string) $event->payload, true);
            // assertEquals, not assertSame: the column is jsonb, which
            // normalises key order on write.
            self::assertEquals([
                'outcome' => 'subdivided',
                'page' => 3,
                'page_size' => 50,
                'depth' => 0,
                'http_status' => 503,
                'sub_count' => 5,
                'sub_size' => 10,
            ], $payload);

            // A sub-page that fails again is recorded too, with its own outcome.
            $this->requestsFor(
                $this->spider(['run_id' => $runId]),
                page: 12,
                pageSize: 10,
                depth: 1,
            );
            $failed = DB::table('scrape_run_events')
                ->where('run_id', $runId)
                ->where('event_type', 'subdivided')
                ->orderByDesc('id')
                ->first();
            self::assertSame(
                'micro_range_failed',
                json_decode((string) $failed->payload, true)['outcome']
            );
        } finally {
            DB::rollBack();
        }
    }
}
