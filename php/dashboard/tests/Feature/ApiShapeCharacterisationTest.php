<?php

declare(strict_types=1);

namespace Tests\Feature;

use BookScraper\Testing\SyntheticShop;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use Symfony\Component\HttpFoundation\StreamedResponse;
use Tests\TestCase;
use Tests\UsesTestDatabase;

/**
 * Every read endpoint, pinned to the response shape Python agreed with.
 *
 * `make api-diff` sends the same 80 requests to both dashboards and compares
 * them field by field — which needs Python. `api_diff --freeze` writes the
 * golden only once all 80 matched, so what is replayed here is Python's
 * contract captured, not PHP's output blessed.
 *
 * Shapes, not payloads: the values are DATA and would change the moment
 * anything is crawled. A shape breaks when a route disappears, a field is
 * renamed or dropped, or a type changes — the regressions worth catching.
 *
 * Ids in the golden are placeholders ({run}, {book}, …) resolved against the
 * synthetic shop, which SyntheticShop builds from nothing before each run.
 * Freezing literal ids would pin them to the database the freeze happened to
 * see; resolving them against "whatever row is first" in a copied catalogue
 * would be worse still, because a detail row that gained or lost a null would
 * change the frozen shape without anything having regressed.
 *
 * Known limit: the LIST endpoints read every shop, so the shape of their first
 * row still comes from copied catalogue data. That is the part of this golden
 * that a reseed could move.
 */
final class ApiShapeCharacterisationTest extends TestCase
{
    use UsesTestDatabase;

    private const GOLDEN = __DIR__ . '/../golden/api_shapes.json';

    private const SYNTHETIC = "(select id from shops where name = 'synthetic')";

    /** Kept in step with ID_PLACEHOLDERS in php/tools/api_diff.py. */
    private const PLACEHOLDERS = [
        '{run}' => 'select id from scrape_runs where shop_id = ' . self::SYNTHETIC
            . ' order by id desc limit 1',
        '{run_scan}' => 'select id from scrape_runs where shop_id = ' . self::SYNTHETIC
            . " and phase = 'scan' order by id desc limit 1",
        '{book}' => "select id from books where source_url like 'https://synthetic.test/%'"
            . ' order by id limit 1',
        '{shop_book}' => 'select id from shop_books where shop_id = ' . self::SYNTHETIC
            . ' order by id limit 1',
        '{issue}' => 'select id from validation_issues where shop_id = ' . self::SYNTHETIC
            . ' order by id limit 1',
        '{url}' => 'select id from discovered_urls where shop_id = ' . self::SYNTHETIC
            . ' order by id limit 1',
        '{cron}' => 'select id from cron_jobs where shop_id = ' . self::SYNTHETIC
            . ' order by id limit 1',
    ];

    /** Endpoints answering with CSV rather than JSON. */
    private const CSV = [
        '/api/books/export?search=Tolkien',
        '/api/books/export?year=1975',
    ];

    protected function setUp(): void
    {
        parent::setUp();
        $this->useTestDatabase();
    }

    #[Group('db')]
    public function test_read_endpoints_keep_their_frozen_shape(): void
    {
        $cases = json_decode((string) file_get_contents(self::GOLDEN), true);
        self::assertIsArray($cases);
        self::assertNotEmpty($cases, 'golden is empty — run `make api-diff-freeze`');

        // Inside a transaction that is rolled back: the fixture this builds
        // is committed data otherwise, and a tool that leaves its fixtures
        // behind breaks the next one. That has already happened three times
        // in this port. The requests below run in-process on this same
        // connection, so they see the uncommitted rows.
        DB::beginTransaction();
        try {
            $ids = $this->resolvePlaceholders();
            $this->compareAll($cases, $ids);
        } finally {
            DB::rollBack();
        }
    }

    /**
     * @param list<array<string, mixed>> $cases
     * @param array<string, string> $ids
     */
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

            // streamedContent() for the CSV exports: they answer with a
            // StreamedResponse, whose getContent() is an empty string.
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

    /** @return array<string, string> placeholder => concrete id */
    private function resolvePlaceholders(): array
    {
        // Rebuilt rather than assumed: after a reseed the runs, cron and
        // issue tables are empty (seed_test_db copies no runs), so half the
        // detail routes would resolve to nothing. build() is idempotent.
        SyntheticShop::build(DB::connection());

        $ids = [];
        foreach (self::PLACEHOLDERS as $token => $query) {
            $value = DB::selectOne($query);
            self::assertNotNull(
                $value,
                "cannot resolve {$token}: no row for `{$query}`. Seed the test database first."
            );
            $ids[$token] = (string) ((array) $value)['id'];
        }

        return $ids;
    }

    /**
     * The response as api_diff saw it, then reduced to its type skeleton.
     *
     * Non-2xx bodies carry `_http_status` because the tool folds the status
     * into the compared value; CSV endpoints are compared as a parsed
     * header/rows pair, not as text.
     */
    private function shapeOf(int $status, string $body, string $endpoint): mixed
    {
        if (in_array($endpoint, self::CSV, true)) {
            $rows = array_map('str_getcsv', array_filter(explode("\n", trim($body)), 'strlen'));
            $header = array_shift($rows) ?: [];
            sort($rows);

            return self::shape(['header' => $header, 'rows' => $rows]);
        }

        // assoc=false so an object stays an object: json_decode(..., true)
        // turns both {} and [] into an empty PHP array, and telling those
        // apart is the point (see the shape() note about "{}").
        $payload = json_decode($body);

        if ($status >= 300) {
            $payload = $payload instanceof \stdClass
                ? (object) (['_http_status' => $status] + get_object_vars($payload))
                : (object) ['_http_status' => $status, '_body' => $payload];
        }

        return self::shape($payload);
    }

    /**
     * Type skeleton: keys and types, no values. Mirrors shape() in
     * php/tools/api_diff.py — int and float both collapse to "number",
     * because one stack computing a count as 12 and the other as 12.0 has
     * never meant anything here.
     */
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
                // An empty list is its own shape: "no rows" and "rows of this
                // form" are different answers.
                return [];
            }
            if (array_is_list($value)) {
                // The first element stands for all of them.
                return [self::shape($value[0])];
            }
            // Only reached for the arrays this test builds itself (the CSV
            // header/rows pair) — decoded JSON objects arrive as stdClass.
            ksort($value);

            return array_map(static fn ($v) => self::shape($v), $value);
        }

        return 'unknown';
    }
}
