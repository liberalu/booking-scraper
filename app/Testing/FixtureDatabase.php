<?php

declare(strict_types=1);

namespace App\Testing;

use App\Schema\Migrator;
use Illuminate\Database\Capsule\Manager as Capsule;
use Illuminate\Database\Connection;
use PDO;
use RuntimeException;

/**
 * A database containing nothing but the synthetic fixture.
 *
 * The dashboard's frozen API shapes could not be made reproducible against the
 * seeded database. Its list endpoints read every shop, so the shape of their
 * first row came from the copied catalogue — and the copy is taken from the
 * live one, which moves. A reseed changed a field from `str` to `null` and the
 * golden failed with nothing having regressed. Re-freezing is not an answer
 * once Python is gone: there would be nothing left to agree with, and the
 * "fix" would be to bless whatever PHP currently emits.
 *
 * So the shapes are frozen over a database built from nothing: the schema
 * baseline in database/schema, then SyntheticShop. Both are code, so the same
 * database comes back every time, with or without Python.
 *
 * Disposable by design — dropped and rebuilt on request, never seeded from
 * anything real.
 */
final class FixtureDatabase
{
    public const NAME = 'book_scraper_php_test_fixture';

    /** The `postgres-test` compose service. 5432 is the real catalogue. */
    private const TEST_PORT = 5433;

    /**
     * Create the database if missing, bring the schema up to date, and build
     * the fixture. Idempotent.
     *
     * @param string $template a DSN on the same cluster, used for its
     *                         credentials and to reach the `postgres` database
     * @return string the fixture database's DSN
     */
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
            // Terminate first: CREATE/DROP DATABASE fails while anything is
            // connected, and a previous run's dashboard may still hold one.
            $admin->exec(
                'select pg_terminate_backend(pid) from pg_stat_activity '
                . "where datname = " . $admin->quote(self::NAME) . ' and pid <> pg_backend_pid()'
            );
            $admin->exec('drop database if exists ' . self::NAME);
        }

        $exists = (bool) $admin->query(
            'select 1 from pg_database where datname = ' . $admin->quote(self::NAME)
        )->fetchColumn();

        if (! $exists) {
            $admin->exec('create database ' . self::NAME);
        }

        // The baseline is the whole schema, so this builds it from empty. No
        // --adopt: nothing here is ever Alembic-stamped.
        (new Migrator(Migrator::connect($dsn), Migrator::defaultDir()))->apply();

        SyntheticShop::build(self::connection($dsn));

        return $dsn;
    }

    /**
     * A connection of its own, deliberately not Database::boot().
     *
     * boot() memoises the first DSN it is given and is set as the global
     * connection; called after something else has booted, it would hand back a
     * connection to a different database and this class would build its fixture
     * there.
     */
    public static function connection(string $dsn): Connection
    {
        $capsule = new Capsule();
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

    /** The fixture database's DSN, on the same cluster as `$template`. */
    public static function dsnFor(string $template): string
    {
        $base = preg_replace('#\+[a-z0-9]+://#', '://', $template) ?? $template;

        return substr($base, 0, (int) strrpos($base, '/')) . '/' . self::NAME;
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

    /**
     * Refuse anything but the test cluster. The port check is load-bearing:
     * this function drops databases, and the real catalogue is the only thing
     * on 5432.
     */
    private static function guard(string $dsn): void
    {
        $port = (int) (self::part($dsn, 'port') ?? 0);
        if ($port !== self::TEST_PORT) {
            throw new RuntimeException(sprintf(
                'refusing to build the fixture database on port %d, not the test '
                . 'cluster (%d). This function drops databases.',
                $port,
                self::TEST_PORT
            ));
        }
    }
}
