<?php

declare(strict_types=1);

namespace BookScraper\Tests;

use BookScraper\Services\ValidateService;
use PHPUnit\Framework\TestCase;
use ReflectionClass;

/**
 * Mirrors tests/unit/test_validate_service_structural.py.
 *
 * These are source-level guards, not behaviour tests: they catch the two
 * regressions that a passing functional suite would still let through.
 */
final class ValidateServiceStructuralTest extends TestCase
{
    private static function source(): string
    {
        return (string) file_get_contents(
            (string) (new ReflectionClass(ValidateService::class))->getFileName()
        );
    }

    public function test_issue_keys_match_the_python_validator(): void
    {
        // Drift here is silent and destructive: resolveGone() closes any open
        // issue this run didn't re-emit, so a key the PHP side spells
        // differently resolves the real backlog and opens a bogus one.
        $pythonSource = (string) file_get_contents(
            __DIR__ . '/../../book_scraper/services/validate.py'
        );
        preg_match('/ISSUE_KEYS[^=]*=\s*frozenset\(\s*\{(.*?)\}\s*\)/s', $pythonSource, $m);
        self::assertNotEmpty($m, 'could not locate ISSUE_KEYS in the Python source');

        preg_match_all('/"([a-z_]+)"/', $m[1], $keys);
        $python = $keys[1];
        sort($python);

        $php = ValidateService::ISSUE_KEYS;
        sort($php);

        self::assertSame($python, $php);
    }

    public function test_the_active_gate_is_written_in_exactly_one_place(): void
    {
        // Seven checks had drifted without the gate, each reopening noise on
        // delisted rows every run. A check that writes its own predicate is
        // what caused that, so the literal must appear once — in the factory.
        self::assertSame(
            1,
            substr_count(self::source(), 'is_active = true'),
            'is_active = true must only appear inside liveBooks(); '
            . 'a check writing its own gate is the drift that caused seven regressions'
        );
    }

    public function test_the_in_stock_gate_is_written_in_exactly_one_place(): void
    {
        self::assertSame(
            1,
            substr_count(self::source(), 'in_stock = true'),
            'in_stock = true must only appear inside liveBooks()'
        );
    }

    public function test_every_check_group_is_called_by_run(): void
    {
        $source = self::source();
        preg_match_all('/public function (check\w+)\(/', $source, $declared);
        preg_match('/public function run\(.*?\n    }/s', $source, $runBody);

        self::assertNotEmpty($runBody, 'could not locate run()');
        foreach ($declared[1] as $method) {
            self::assertStringContainsString(
                "\$this->{$method}(",
                $runBody[0],
                "run() never calls {$method}() — its findings would silently never fire"
            );
        }
    }
}
