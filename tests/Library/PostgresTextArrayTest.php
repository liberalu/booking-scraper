<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Casts\PostgresTextArray;
use App\Support\Database;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class PostgresTextArrayTest extends TestCase
{
    public static function arrays(): array
    {
        return [
            'empty' => [[]],
            'plain' => [['Romanai']],
            'diacritics' => [['Grožinė literatūra', 'Romanai']],
            'embedded comma' => [['Knygos, žurnalai', 'Kita']],
            'embedded quotes' => [['say "hi"']],
            'backslash' => [['a\\b']],
            'braces' => [['{not an array}']],
            'lookalike null' => [['NULL']],
            'breadcrumb' => [['Pradžia', 'Knygos', 'Grožinė literatūra', 'Romanai']],
        ];
    }

    #[DataProvider('arrays')]
    public function test_round_trips_through_postgres(array $items): void
    {
        $connection = Database::boot($this->dsn())->getConnection();

        $literal = $connection->selectOne(
            'select (?::text[])::text as arr',
            [PostgresTextArray::encode($items)]
        )->arr;

        self::assertSame($items, PostgresTextArray::parse((string) $literal));
    }

    public function test_server_emitted_literal_parses(): void
    {
        $connection = Database::boot($this->dsn())->getConnection();
        $literal = (string) $connection->selectOne(
            "select array['Grožinė literatūra','Knygos, žurnalai','say \"hi\"']::text as arr"
        )->arr;

        self::assertSame(
            ['Grožinė literatūra', 'Knygos, žurnalai', 'say "hi"'],
            PostgresTextArray::parse($literal)
        );
    }

    private function dsn(): string
    {
        return getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test';
    }
}
