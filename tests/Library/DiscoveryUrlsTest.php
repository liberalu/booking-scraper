<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Discovery\GraphQlUrls;
use App\Discovery\IbibliotekaApiUrls;
use App\Discovery\LupaSearchUrls;
use PHPUnit\Framework\TestCase;

final class DiscoveryUrlsTest extends TestCase
{
    private static function golden(): array
    {
        $path = __DIR__.'/../golden/discovery_urls.json';
        self::assertFileExists($path, 'run `make discovery-golden` first');

        return json_decode((string) file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
    }

    public function test_graph_ql_urls_match_python(): void
    {
        foreach (self::golden()['graphql'] as $case) {
            $url = GraphQlUrls::buildPageUrl(
                $case['base_url'],
                $case['category_ids'],
                $case['page_size'],
                $case['page'],
                $case['subdivision_depth'],
            );
            self::assertSame($case['url'], $url, "graphql url: {$case['label']}");
            self::assertSame(
                $case['parsed'],
                GraphQlUrls::parsePageUrl($url),
                "graphql parse: {$case['label']}"
            );
        }
    }

    public function test_subdivision_depth_survives_the_round_trip(): void
    {
        $url = GraphQlUrls::buildPageUrl('https://x.lt', ['1', '2'], 10, 4, 1);
        self::assertSame(1, GraphQlUrls::parsePageUrl($url)['subdivision_depth']);
        self::assertSame(
            0,
            GraphQlUrls::parsePageUrl(
                GraphQlUrls::buildPageUrl('https://x.lt', ['1', '2'], 10, 4)
            )['subdivision_depth']
        );
    }

    public function test_lupa_search_urls_match_python(): void
    {
        foreach (self::golden()['lupasearch'] as $case) {
            $seed = LupaSearchUrls::buildSeedUrl(
                $case['endpoint'],
                $case['category_ids'],
                $case['page_size'],
                $case['extra_filters'],
            );
            self::assertSame($case['seed_url'], $seed, "lupa seed: {$case['label']}");
            self::assertSame(
                $case['offsets'],
                LupaSearchUrls::parseOffsets($seed),
                "lupa offsets: {$case['label']}"
            );

            $advanced = LupaSearchUrls::advance($seed, $case['page_size'] * 3);
            self::assertSame($case['advanced_url'], $advanced, "lupa advance: {$case['label']}");
            self::assertSame(
                $case['advanced_offsets'],
                LupaSearchUrls::parseOffsets($advanced)
            );

            self::assertSame(
                $case['seed_request'],
                LupaSearchUrls::postRequest($seed),
                "lupa body: {$case['label']}"
            );
            self::assertSame(
                $case['advanced_request'],
                LupaSearchUrls::postRequest($advanced),
                "lupa advanced body: {$case['label']}"
            );
        }
    }

    public function test_dotted_filter_keys_survive_parsing(): void
    {
        $seed = LupaSearchUrls::buildSeedUrl(
            'https://api.lupasearch.com/v1/query/x',
            ['1'],
            42,
            ['publisher' => ['Alma littera']],
        );
        $body = json_decode(LupaSearchUrls::postRequest($seed)['body'], true);
        self::assertSame(['Alma littera'], $body['filters']['publisher']);
    }

    public function test_ibiblioteka_urls_match_python(): void
    {
        foreach (self::golden()['ibiblioteka_api'] as $case) {
            $seeds = IbibliotekaApiUrls::buildSeedUrls(
                $case['year_from'],
                $case['year_to'],
                $case['page_size'],
            );
            self::assertSame($case['seed_urls'], $seeds, "ibib seeds: {$case['label']}");
            self::assertSame(
                $case['params'],
                IbibliotekaApiUrls::parseParams($seeds[0]),
                "ibib params: {$case['label']}"
            );

            $advanced = IbibliotekaApiUrls::advance($seeds[0], $case['page_size'] * 2);
            self::assertSame($case['advanced_url'], $advanced, "ibib advance: {$case['label']}");
            self::assertSame(
                $case['advanced_params'],
                IbibliotekaApiUrls::parseParams($advanced)
            );
            self::assertSame(
                $case['seed_request'],
                IbibliotekaApiUrls::postRequest($seeds[0]),
                "ibib body: {$case['label']}"
            );

            self::assertSame(
                $case['legacy_params'],
                IbibliotekaApiUrls::parseParams($case['legacy_url']),
                "ibib legacy params: {$case['label']}"
            );
            self::assertSame(
                $case['legacy_advanced'],
                IbibliotekaApiUrls::advance($case['legacy_url'], 400),
                "ibib legacy advance: {$case['label']}"
            );
            self::assertSame(
                $case['legacy_request'],
                IbibliotekaApiUrls::postRequest($case['legacy_url']),
                "ibib legacy body: {$case['label']}"
            );
        }
    }

    public function test_monthly_bands_cover_every_month(): void
    {
        $seeds = IbibliotekaApiUrls::buildSeedUrls(2023, 2025, 100);
        self::assertCount(24, $seeds);
        self::assertStringContainsString('df=2023-12-01&dt=2024-01-01', $seeds[11]);
    }
}
