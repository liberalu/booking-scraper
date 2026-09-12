<?php

declare(strict_types=1);

namespace Tests\Crawler;

use App\Support\CrawlSpawner;
use App\Support\Database;
use PHPUnit\Framework\TestCase;
use ReflectionMethod;

final class CrawlSpawnerDatabaseUrlTest extends TestCase
{
    public function test_a_crawl_process_spawns_into_the_database_it_is_using(): void
    {
        $dsn = getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test';
        Database::boot($dsn);

        $spawner = new CrawlSpawner;
        $method = new ReflectionMethod($spawner, 'databaseUrl');

        self::assertSame($dsn, $method->invoke($spawner));
    }
}
