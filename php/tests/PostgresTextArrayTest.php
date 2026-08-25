<?php

declare(strict_types=1);

namespace BookScraper\Tests;

use BookScraper\Casts\PostgresTextArray;
use BookScraper\Database;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

/**
 * Round-trips through a real Postgres text[] rather than asserting against
 * hand-written literals: the point of the cast is to agree with what the
 * server actually emits, including its quoting and escaping rules.
 */
final class PostgresTextArrayTest extends TestCase
{
    /** @return list<array{0: list<string>}> */
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

    /** @param list<string> $items */
    #[DataProvider('arrays')]
    public function test_round_trips_through_postgres(array $items): void
    {
        $connection = Database::boot(self::dsn())->getConnection();

        // Send our encoding to the server, read back the server's own
        // literal, and parse that. Agreement in both directions or bust.
        $literal = $connection->selectOne(
            'select (?::text[])::text as arr',
            [PostgresTextArray::encode($items)]
        )->arr;

        self::assertSame($items, PostgresTextArray::parse((string) $literal));
    }

    public function test_server_emitted_literal_parses(): void
    {
        $connection = Database::boot(self::dsn())->getConnection();
        $literal = (string) $connection->selectOne(
            "select array['Grožinė literatūra','Knygos, žurnalai','say \"hi\"']::text as arr"
        )->arr;

        self::assertSame(
            ['Grožinė literatūra', 'Knygos, žurnalai', 'say "hi"'],
            PostgresTextArray::parse($literal)
        );
    }

    private static function dsn(): string
    {
        return getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_test';
    }
}
