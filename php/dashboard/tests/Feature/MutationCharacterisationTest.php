<?php

declare(strict_types=1);

namespace Tests\Feature;

use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use Tests\TestCase;
use Tests\UsesTestDatabase;

/**
 * Every write route, pinned to behaviour Python agreed with.
 *
 * `make mutation-diff` clones the test database per stack, starts both
 * dashboards, and sends 100 requests to each — which needs Python. The cases
 * are frozen instead: `mutation_diff --freeze` writes them only once every one
 * matched, so what is replayed here is Python's behaviour captured.
 *
 * Driven in-process through Laravel's HTTP layer rather than over a socket. No
 * server to start or tear down, and it exercises the same routes, middleware
 * and controllers the socket version did.
 *
 * Order matters: the cases accumulate state deliberately — a run is stopped
 * before something else asserts it cannot be stopped again — so they replay as
 * one sequence, not one test each.
 *
 * Ids in the golden are labels (`<run_running>`), because the real ones move
 * every run. They are resolved against the fixtures this test plants, and the
 * responses are normalised back the same way before comparing.
 */
final class MutationCharacterisationTest extends TestCase
{
    use UsesTestDatabase;

    private const GOLDEN = __DIR__ . '/../golden/mutation_cases.json';

    /**
     * The SAME marker mutation_diff.py plants with, deliberately.
     *
     * bulk-rescrape answers with a list of URLs, so the marker is part of a
     * frozen expected value. A second marker here would mean the golden could
     * never match. The two never run at once, and this test rolls back while
     * the tool cleans up after itself, so sharing the marker costs nothing.
     */
    private const MARK = 'mutation-diff';

    /** Keys whose integer value is a row id — everything else is a count. */
    private const ID_KEYS = [
        'id', 'run_id', 'shop_book_id', 'previous_book_id', 'existing_book_id',
        'chain_to_id', 'cron_job_id',
    ];

    /** @var array<string, int> label => planted row id */
    private array $ids = [];

    protected function setUp(): void
    {
        parent::setUp();
        $this->useTestDatabase();
    }

    #[Group('db')]
    public function testEveryFrozenCaseStillBehavesTheSame(): void
    {
        $cases = self::golden();
        self::assertGreaterThanOrEqual(100, count($cases), 'the golden has shrunk');

        DB::beginTransaction();
        try {
            $this->plantFixtures();
            $labels = array_flip($this->ids);

            foreach ($cases as $case) {
                $path = $this->resolveLabels($case['path']);
                $body = $this->resolveBodyLabels($case['body']);

                // The pre-SPA endpoints under /shops take form fields and
                // answer with HTML; FastAPI declares them with Form(...), so
                // the comparison sent them form-encoded and stored the body as
                // {"_raw": ...} when it would not parse as JSON. Mirror both,
                // or these six cases compare a null body against markup.
                $response = str_starts_with($path, '/shops/')
                    ? $this->post($path, $body ?? [])
                    : $this->json($case['method'], $path, $body ?? []);

                $content = (string) $response->getContent();
                $decoded = json_decode($content, true);
                $actual = [
                    '_status' => $response->getStatusCode(),
                    'body' => json_last_error() === JSON_ERROR_NONE
                        ? $decoded
                        : ['_raw' => mb_substr($content, 0, 400)],
                ];
                if ($response->headers->has('Location')) {
                    $actual['_location'] = $response->headers->get('Location');
                }

                self::assertEquals(
                    $case['expected'],
                    self::normalise($actual, $labels),
                    "write-route behaviour changed for: {$case['label']} "
                    . "({$case['method']} {$case['path']})"
                );
            }
        } finally {
            DB::rollBack();
        }
    }

    /** The same shapes mutation_diff plants, so the frozen cases still apply. */
    private function plantFixtures(): void
    {
        $shopId = (int) DB::table('shops')->orderBy('id')->value('id');
        self::assertNotSame(0, $shopId, 'the test database has no shops — seed it first');

        foreach ([
            'running' => ['scan', 'running'],
            'running2' => ['scan', 'running'],
            'completed' => ['scan', 'completed'],
            'failed_pending' => ['scan', 'failed'],
            'failed_empty' => ['scan', 'failed'],
            'discover' => ['discover_sitemap', 'completed'],
        ] as $key => [$phase, $status]) {
            $this->ids["run_{$key}"] = (int) DB::selectOne(
                "insert into scrape_runs (shop_id, phase, status, started_at,
                     urls_total, urls_processed, items_added, items_updated,
                     errors_4xx, errors_5xx, error_count, last_heartbeat,
                     close_reason, finished_at)
                 values (?, ?, ?, now() - interval '10 minutes', 10, 5, 0, 0,
                     0, 0, 0, now(), ?,
                     case when ? <> 'running' then now() end)
                 returning id",
                [$shopId, $phase, $status, self::MARK, $status]
            )->id;
        }

        DB::insert(
            "insert into scrape_url_items (run_id, shop_id, url, url_type, status,
                 created_at, attempts)
             values (?, ?, ?, 'product', 'pending', now(), 0)",
            [$this->ids['run_failed_pending'], $shopId,
                'https://example.test/' . self::MARK . '/pending']
        );

        $itemId = (int) DB::selectOne(
            "insert into scrape_url_items (run_id, shop_id, url, url_type, status,
                 created_at, attempts)
             values (?, ?, ?, 'product', 'failed', now(), 1) returning id",
            [$this->ids['run_running'], $shopId,
                'https://example.test/' . self::MARK . '/1']
        )->id;
        foreach ([['http_404', 404], [null, null]] as [$reason, $status]) {
            DB::insert(
                "insert into scrape_failures (scrape_url_item_id, run_id, shop_id, url,
                     occurred_at, error_reason, http_status, lifecycle_state)
                 values (?, ?, ?, ?, now(), ?, ?, 'new')",
                [$itemId, $this->ids['run_running'], $shopId,
                    'https://example.test/' . self::MARK . '/1', $reason, $status]
            );
        }

        // Created, not borrowed. Selecting "the three lowest-id books with a
        // product URL" made bulk-rescrape's expected value — a list of URLs —
        // depend on which shop happened to hold those ids, so the frozen case
        // broke whenever the seeded catalogue shifted.
        $linkedBooks = [];
        for ($n = 0; $n < 3; $n++) {
            $url = 'https://example.test/' . self::MARK . '/book/' . $n;
            $linkedBooks[] = (int) DB::selectOne(
                "insert into shop_books (shop_id, url, title, type, is_active,
                     in_stock, match_status, first_seen_at, last_seen_at)
                 values (?, ?, ?, 'book', true, true, 'unmatched', now(), now())
                 returning id",
                [$shopId, $url, "Fixture Book {$n}"]
            )->id;
            DB::insert(
                "insert into discovered_urls (shop_id, url, normalized_url, source,
                     url_type, fail_count, first_seen_at, last_seen_at, shop_book_id)
                 values (?, ?, ?, 'sitemap', 'product', 0, now(), now(), ?)",
                [$shopId, $url, $url, end($linkedBooks)]
            );
        }

        $index = 0;
        foreach ([
            'new' => ['missing_isbn', 'new'],
            'new2' => ['missing_isbn', 'new'],
            'acked' => ['missing_isbn', 'acknowledged'],
            'other' => ['price_zero', 'new'],
        ] as $key => [$issue, $state]) {
            $this->ids["issue_{$key}"] = (int) DB::selectOne(
                "insert into validation_issues (shop_id, last_seen_run_id, url, field,
                     issue, run_count, lifecycle_state, acknowledged_at, shop_book_id)
                 values (?, ?, ?, 'isbn', ?, 1, ?,
                     case when ? = 'acknowledged' then now() end, ?)
                 returning id",
                [$shopId, $this->ids['run_completed'],
                    'https://example.test/' . self::MARK . '/' . $key,
                    $issue, $state, $state, $linkedBooks[$index] ?? null]
            )->id;
            $index++;
        }

        foreach ([
            'a' => ['discover', 'sitemap'],
            'b' => ['scan', null],
            'target' => ['discover', 'categories'],
            'dependent' => ['scan', null],
            'doomed' => ['scan', null],
        ] as $key => [$phase, $strategy]) {
            $this->ids["cron_{$key}"] = (int) DB::selectOne(
                "insert into cron_jobs (shop_id, phase, strategy, args,
                     cron_expression, enabled, created_at)
                 values (?, ?, ?, ?, '0 2 * * *', true, now()) returning id",
                [$shopId, $phase, $strategy, self::MARK]
            )->id;
        }
        DB::update('update cron_jobs set chain_to_job_id = ? where id = ?',
            [$this->ids['cron_target'], $this->ids['cron_dependent']]);

        $linked = DB::table('shop_books')->whereNotNull('book_id')->orderBy('id')->value('id');
        self::assertNotNull($linked, 'no linked shop_book to unlink — seed the database');
        $this->ids['shop_book_linked'] = (int) $linked;
    }

    private function resolveLabels(string $path): string
    {
        foreach ($this->ids as $label => $id) {
            $path = str_replace("<{$label}>", (string) $id, $path);
        }

        return $path;
    }

    /** @param array<string, mixed>|null $body */
    private function resolveBodyLabels(?array $body): ?array
    {
        if ($body === null) {
            return null;
        }

        $out = [];
        foreach ($body as $key => $value) {
            if (is_array($value)) {
                $out[$key] = $this->resolveBodyLabels($value);
            } elseif (is_string($value) && in_array($key, self::ID_KEYS, true)
                && isset($this->ids[$value])) {
                $out[$key] = $this->ids[$value];
            } else {
                $out[$key] = $value;
            }
        }

        return $out;
    }

    /**
     * The same normalisation mutation_diff applies before freezing.
     *
     * Key-gated, never value-gated. Substituting any id-shaped integer
     * corrupts a count that happens to collide with a fixture id — `days: 30`
     * did exactly that while this was being written.
     *
     * @param array<int, string> $labels
     */
    private static function normalise(mixed $value, array $labels, string $key = ''): mixed
    {
        if (is_bool($value)) {
            return $value;
        }
        if (is_int($value)) {
            if (!in_array($key, self::ID_KEYS, true)) {
                return $value;
            }

            return $labels[$value] ?? '<id>';
        }
        if (is_string($value)) {
            if (preg_match('/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?'
                . '([+-]\d{2}:?\d{2}|Z)?$/', $value) === 1) {
                return '<timestamp>';
            }

            return preg_replace('/(run #)\d+/', '$1<id>', $value) ?? $value;
        }
        if (is_array($value)) {
            $out = [];
            foreach ($value as $k => $v) {
                $out[$k] = self::normalise($v, $labels, is_string($k) ? $k : $key);
            }

            return $out;
        }

        return $value;
    }

    /** @return list<array<string, mixed>> */
    private static function golden(): array
    {
        self::assertFileExists(
            self::GOLDEN,
            'run `make mutation-diff FREEZE=1` while Python still exists'
        );

        return json_decode((string) file_get_contents(self::GOLDEN), true, 512, JSON_THROW_ON_ERROR);
    }
}
