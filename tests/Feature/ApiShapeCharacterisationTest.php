<?php

declare(strict_types=1);

namespace Tests\Feature;

use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use Symfony\Component\HttpFoundation\StreamedResponse;
use Tests\Support\FixtureDatabase;
use Tests\TestCase;
use Tests\UsesTestDatabase;

final class ApiShapeCharacterisationTest extends TestCase
{
    use UsesTestDatabase;

    private const GOLDEN = __DIR__.'/../golden/api_shapes.json';

    private const SYNTHETIC = "(select id from shops where name = 'synthetic')";

    private const PLACEHOLDERS = [

        '{run}' => 'select id from scrape_runs where shop_id = '.self::SYNTHETIC
            .' order by id limit 1',
        '{run_scan}' => 'select id from scrape_runs where shop_id = '.self::SYNTHETIC
            ." and phase = 'scan' order by id limit 1",
        '{book}' => 'select book_id from shop_books where book_id is not null '
            .'order by id limit 1',
        '{shop_book}' => 'select id from shop_books where shop_id = '.self::SYNTHETIC
            .' order by id limit 1',
        '{issue}' => 'select id from validation_issues where shop_id = '.self::SYNTHETIC
            .' order by id limit 1',
        '{url}' => 'select id from discovered_urls where shop_id = '.self::SYNTHETIC
            .' order by id limit 1',
        '{cron}' => 'select id from cron_jobs where shop_id = '.self::SYNTHETIC
            .' order by id limit 1',

        '{shop}' => 'select name from shops order by id limit 1',
        '{isbn}' => 'select isbn from book_isbns order by isbn limit 1',

        '{title}' => 'select title from books order by id limit 1',
        '{year}' => 'select year from books where year is not null order by year limit 1',
        '{issue_type}' => 'select issue from validation_issues order by issue limit 1',
    ];

    private const CSV = [
        '/api/books/export?search={title}',
        '/api/books/export?year={year}',
    ];

    protected function setUp(): void
    {
        parent::setUp();

        $this->useTestDatabase(FixtureDatabase::ensure(
            getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test',
            recreate: true
        ));
    }

    #[Group('db')]
    public function test_read_endpoints_keep_their_frozen_shape(): void
    {
        $cases = json_decode((string) file_get_contents(self::GOLDEN), true);
        self::assertIsArray($cases);
        self::assertNotEmpty($cases, 'golden is empty — run `make api-diff-freeze`');

        $this->compareAll($cases, $this->resolvePlaceholders());
    }

    private function compareAll(array $cases, array $ids): void
    {
        foreach ($cases as $case) {
            $endpoint = strtr($case['endpoint'], $ids);
            $response = $this->get($endpoint);

            self::assertSame(
                $case['status'],
                $response->getStatusCode(),
                "status changed for {$case['endpoint']}"
            );

            $body = $response->baseResponse instanceof StreamedResponse
                ? $response->streamedContent()
                : (string) $response->getContent();

            self::assertSame(
                $case['shape'],
                $this->shapeOf($response->getStatusCode(), $body, $case['endpoint']),
                "response shape changed for {$case['endpoint']}"
            );
        }
    }

    private function resolvePlaceholders(): array
    {
        $ids = [];
        foreach (self::PLACEHOLDERS as $token => $query) {
            $value = DB::selectOne($query);
            self::assertNotNull(
                $value,
                "cannot resolve {$token}: no row for `{$query}`. Seed the test database first."
            );

            $ids[$token] = rawurlencode((string) array_values((array) $value)[0]);
        }

        return $ids;
    }

    private function shapeOf(int $status, string $body, string $endpoint): mixed
    {
        if (in_array($endpoint, self::CSV, true)) {
            $rows = array_map('str_getcsv', array_filter(explode("\n", trim($body)), 'strlen'));
            $header = array_shift($rows) ?: [];
            sort($rows);

            return self::shape(['header' => $header, 'rows' => $rows]);
        }

        $payload = json_decode($body);

        if ($status >= 300) {
            $payload = $payload instanceof \stdClass
                ? (object) (['_http_status' => $status] + get_object_vars($payload))
                : (object) ['_http_status' => $status, '_body' => $payload];
        }

        return self::shape($payload);
    }

    private static function shape(mixed $value): mixed
    {
        if ($value === null) {
            return 'null';
        }
        if (is_bool($value)) {
            return 'bool';
        }
        if (is_int($value) || is_float($value)) {
            return 'number';
        }
        if (is_string($value)) {
            return 'str';
        }
        if ($value instanceof \stdClass) {
            $map = get_object_vars($value);
            if ($map === []) {
                return '{}';
            }
            ksort($map);

            return array_map(static fn ($v) => self::shape($v), $map);
        }
        if (is_array($value)) {
            if ($value === []) {

                return [];
            }
            if (array_is_list($value)) {

                return [self::shape($value[0])];
            }

            ksort($value);

            return array_map(static fn ($v) => self::shape($v), $value);
        }

        return 'unknown';
    }
}
