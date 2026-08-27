<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Services\ValidateService;
use PHPUnit\Framework\TestCase;
use ReflectionClass;

/**
 * Source-level guards, not behaviour tests: they catch the regressions a
 * passing functional suite would still let through.
 *
 * A third guard used to live here, comparing ISSUE_KEYS against the Python
 * validator's frozenset. It moved to the dashboard suite when Python was
 * removed, re-pointed at the invariant that survives: every key the validator
 * can emit needs a severity and a description, or the UI renders an issue it
 * cannot label. The frozen `validate_findings.json` covers the other half — a
 * renamed key changes the findings it records.
 */
final class ValidateServiceStructuralTest extends TestCase
{
    private static function source(): string
    {
        return (string) file_get_contents(
            (string) (new ReflectionClass(ValidateService::class))->getFileName()
        );
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
