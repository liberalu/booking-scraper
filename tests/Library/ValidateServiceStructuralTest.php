<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Repositories\ValidationRepository;
use App\Services\ValidateService;
use PHPUnit\Framework\TestCase;
use ReflectionClass;

final class ValidateServiceStructuralTest extends TestCase
{
    private function source(): string
    {
        return (string) file_get_contents(
            (string) (new ReflectionClass(ValidationRepository::class))->getFileName()
        );
    }

    public function test_the_active_gate_is_written_in_exactly_one_place(): void
    {

        self::assertSame(
            1,
            substr_count($this->source(), 'is_active = true'),
            'is_active = true must only appear inside liveBooks(); '
            .'a check writing its own gate is the drift that caused seven regressions'
        );
    }

    public function test_the_in_stock_gate_is_written_in_exactly_one_place(): void
    {
        self::assertSame(
            1,
            substr_count($this->source(), 'in_stock = true'),
            'in_stock = true must only appear inside liveBooks()'
        );
    }

    public function test_every_check_group_is_called_by_run(): void
    {
        $repositorySource = $this->source();
        $serviceSource = (string) file_get_contents(
            (string) (new ReflectionClass(ValidateService::class))->getFileName()
        );
        preg_match_all('/public function (check\w+)\(/', $repositorySource, $declared);
        preg_match('/public function run\(.*?\n    }/s', $serviceSource, $runBody);

        self::assertNotEmpty($runBody, 'could not locate run()');
        foreach ($declared[1] as $method) {
            self::assertStringContainsString(
                "\$this->validation->{$method}(",
                $runBody[0],
                "run() never calls {$method}() — its findings would silently never fire"
            );
        }
    }
}
