<?php

declare(strict_types=1);

namespace App\Services\Legacy;

use App\DTO\LegacyAction;
use App\DTO\ReadModel\ShopUrlBatch;
use App\DTO\Request\LegacyFormInput;
use App\Exceptions\ActionFailed;
use App\Models\DiscoveredUrl;
use App\Models\Shop;
use App\Repositories\LegacyFormsRepository;
use App\Support\CrawlSpawner;
use Throwable;

final readonly class LegacyFormsService
{
    private const int MAX_FILTERED_URLS = 5000;

    public function __construct(private LegacyFormsRepository $forms) {}

    public function rateSettings(LegacyFormInput $input, Shop $shop): LegacyAction
    {
        if ($input->downloadDelay < 0.1 || $input->downloadDelay > 60.0) {
            throw ActionFailed::badRequest(['detail' => 'download_delay must be 0.1–60 s']);
        }
        if ($input->concurrentRequestsPerDomain < 1 || $input->concurrentRequestsPerDomain > 16) {
            throw ActionFailed::badRequest([
                'detail' => 'concurrent_requests_per_domain must be 1–16',
            ]);
        }

        $this->forms->saveRateSettings(
            $shop->id,
            $input->downloadDelay,
            $input->concurrentRequestsPerDomain,
        );

        return LegacyAction::html('<p class="success">Saved.</p>');
    }

    public function scrapeUrl(DiscoveredUrl $url): LegacyAction
    {
        $shop = $this->forms->shopNameForUrl($url);
        if ($shop === null) {
            throw ActionFailed::notFound(['detail' => 'Shop not found for URL']);
        }

        $this->spawn($shop, [$url->url]);

        return LegacyAction::redirect('/urls/'.$url->id.'?scraped=1');
    }

    public function scrapeUnknownUrls(LegacyFormInput $input): LegacyAction
    {
        $batches = $this->forms->unknownUrlBatches($input->shop);
        $started = 0;
        foreach ($batches as $batch) {
            $this->spawn($batch->shop, $batch->urls);
            $started += count($batch->urls);
        }

        return LegacyAction::redirect(
            "/urls?shop={$input->shop}&url_type=unknown&scrape_started={$started}",
        );
    }

    public function scrapeFiltered(LegacyFormInput $input): LegacyAction
    {
        if (! $this->hasFilter($input)) {
            throw ActionFailed::badRequest([
                'detail' => 'At least one filter is required '
                    .'(shop/q/author/publisher/category/format/missing/active/'
                    .'has_isbn/field filters)',
            ]);
        }
        if ($input->shop !== '' && ! $this->forms->shopExists($input->shop)) {
            throw ActionFailed::notFound(['detail' => "Unknown shop: {$input->shop}"]);
        }

        $batches = $this->forms->filteredShopBookBatches($input, self::MAX_FILTERED_URLS + 1);
        $count = array_sum(array_map(
            static fn (ShopUrlBatch $batch): int => count($batch->urls),
            $batches,
        ));
        if ($count === 0) {
            throw ActionFailed::notFound(['detail' => 'No shop_books matched the filters']);
        }
        if ($count > self::MAX_FILTERED_URLS) {
            throw ActionFailed::payloadTooLarge([
                'detail' => sprintf(
                    'Filter matches %d+ shop_books — over the %d cap. Narrow the '
                    .'filter, pick a shop, or run `scrapy crawl scan` for a full pass.',
                    $count,
                    self::MAX_FILTERED_URLS,
                ),
            ]);
        }

        $jobs = [];
        foreach ($batches as $batch) {
            $spawn = $this->spawn($batch->shop, $batch->urls);
            $jobs[] = [
                'shop' => $batch->shop,
                'urls_count' => count($batch->urls),
                'pid' => $spawn['pid'],
                'command' => implode(' ', array_slice($spawn['cmd'], 0, 4))
                    ." --shop={$batch->shop} --urls=<".count($batch->urls).' urls>',
            ];
        }

        if ($input->output === 'json') {
            return LegacyAction::accepted([
                'status' => 'started',
                'urls_count' => $count,
                'jobs' => $jobs,
            ]);
        }

        $back = array_filter([
            'shop' => $input->shop,
            'q' => $input->search,
            'author' => $input->author,
            'publisher' => $input->publisher,
            'category' => $input->category,
            'format' => $input->format,
            'missing' => $input->missing,
            'active' => $input->active,
        ], static fn (string $value): bool => $value !== '');
        if ($input->hasIsbn) {
            $back['has_isbn'] = 'true';
        }
        $back['scrape_started'] = (string) $count;

        return LegacyAction::redirect('/shop-books?'.http_build_query($back));
    }

    private function hasFilter(LegacyFormInput $input): bool
    {
        return $input->hasIsbn || implode('', [
            $input->shop,
            $input->search,
            $input->author,
            $input->publisher,
            $input->category,
            $input->format,
            $input->missing,
            $input->active,
        ]) !== '';
    }

    /**
     * @param  list<string>  $urls
     * @return array{log: string, pid: int|null, cmd: list<string>}
     */
    private function spawn(string $shop, array $urls): array
    {
        try {
            return CrawlSpawner::spawn('scan', $shop, urls: implode(',', $urls));
        } catch (Throwable $e) {
            throw ActionFailed::unavailable(['detail' => $e->getMessage()]);
        }
    }
}
