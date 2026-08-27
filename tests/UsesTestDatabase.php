<?php

declare(strict_types=1);

namespace Tests;

use Illuminate\Support\Facades\DB;

/**
 * Point the default connection at the Postgres test database.
 *
 * phpunit.xml pins the Laravel skeleton default of sqlite::memory:. The
 * dashboard's queries are all raw Postgres — partial indexes, ON CONFLICT,
 * text[] arrays — so the connection is redirected per-test rather than
 * globally, leaving the rest of the suite on sqlite.
 */
trait UsesTestDatabase
{
    protected function useTestDatabase(?string $dsn = null): void
    {
        $dsn ??= getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test';
        $parts = parse_url($dsn);
        config([
            'database.default' => 'pgsql',
            'database.connections.pgsql.driver' => 'pgsql',
            'database.connections.pgsql.host' => $parts['host'] ?? '127.0.0.1',
            'database.connections.pgsql.port' => $parts['port'] ?? 5433,
            'database.connections.pgsql.database' => ltrim($parts['path'] ?? '', '/'),
            'database.connections.pgsql.username' => $parts['user'] ?? 'postgres',
            'database.connections.pgsql.password' => $parts['pass'] ?? 'postgres',
            'database.connections.pgsql.search_path' => 'public',
        ]);
        DB::purge('pgsql');
    }
}
