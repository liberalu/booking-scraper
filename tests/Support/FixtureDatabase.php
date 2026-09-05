<?php

declare(strict_types=1);

namespace Tests\Support;

use App\Schema\Migrator;
use Illuminate\Database\Capsule\Manager as Capsule;
use Illuminate\Database\Connection;
use PDO;
use RuntimeException;

final class FixtureDatabase
{
    public const string NAME = 'book_scraper_php_test_fixture';

    private const int TEST_PORT = 5433;

    public static function ensure(string $template, bool $recreate = false): string
    {
        $dsn = self::dsnFor($template);
        self::guard($dsn);

        $admin = new PDO(
            self::pdoDsn($dsn, 'postgres'),
            self::part($dsn, 'user') ?? 'postgres',
            self::part($dsn, 'pass') ?? 'postgres',
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
        );

        if ($recreate) {

            $admin->exec(
                'select pg_terminate_backend(pid) from pg_stat_activity '
                .'where datname = '.$admin->quote(self::NAME).' and pid <> pg_backend_pid()'
            );
            $admin->exec('drop database if exists '.self::NAME);
        }

        $exists = (bool) $admin->query(
            'select 1 from pg_database where datname = '.$admin->quote(self::NAME)
        )->fetchColumn();

        if (! $exists) {
            $admin->exec('create database '.self::NAME);
        }

        (new Migrator(Migrator::connect($dsn), Migrator::defaultDir()))->apply();

        SyntheticShop::build(self::connection($dsn));

        return $dsn;
    }

    public static function connection(string $dsn): Connection
    {
        $capsule = new Capsule;
        $capsule->addConnection([
            'driver' => 'pgsql',
            'host' => self::part($dsn, 'host') ?? '127.0.0.1',
            'port' => self::part($dsn, 'port') ?? (string) self::TEST_PORT,
            'database' => ltrim(self::part($dsn, 'path') ?? '', '/'),
            'username' => self::part($dsn, 'user') ?? 'postgres',
            'password' => self::part($dsn, 'pass') ?? 'postgres',
            'charset' => 'utf8',
            'schema' => 'public',
        ]);

        return $capsule->getConnection();
    }

    public static function dsnFor(string $template): string
    {
        $base = preg_replace('#\+[a-z0-9]+://#', '://', $template) ?? $template;

        return substr($base, 0, (int) strrpos($base, '/')).'/'.self::NAME;
    }

    private static function pdoDsn(string $dsn, string $database): string
    {
        return sprintf(
            'pgsql:host=%s;port=%s;dbname=%s',
            self::part($dsn, 'host') ?? '127.0.0.1',
            self::part($dsn, 'port') ?? self::TEST_PORT,
            $database
        );
    }

    private static function part(string $dsn, string $key): ?string
    {
        $parts = parse_url($dsn);

        return isset($parts[$key]) ? (string) $parts[$key] : null;
    }

    private static function guard(string $dsn): void
    {
        $port = (int) (self::part($dsn, 'port') ?? 0);
        if ($port !== self::TEST_PORT) {
            throw new RuntimeException(sprintf(
                'refusing to build the fixture database on port %d, not the test '
                .'cluster (%d). This function drops databases.',
                $port,
                self::TEST_PORT
            ));
        }
    }
}
