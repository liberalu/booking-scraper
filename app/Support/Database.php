<?php

declare(strict_types=1);

namespace App\Support;

use Illuminate\Container\Container;
use Illuminate\Database\Capsule\Manager as Capsule;
use Illuminate\Support\Facades\Facade;
use RuntimeException;

/**
 * Eloquent bootstrap against the EXISTING Postgres schema.
 *
 * Alembic remains the sole migration owner — there are no PHP migrations
 * and there must not be. The Python stack and this one run against one
 * catalogue during the port, which is what makes differential
 * verification possible; a second migration tool pointed at the same
 * tables would end that.
 */
final class Database
{
    private static ?Capsule $capsule = null;

    /** The container boot() built, kept so the facade root can be rebound. */
    private static ?Container $container = null;

    /**
     * The DSN boot() actually used.
     *
     * Load-bearing: the failsafe and watchdog open their own connections,
     * and resolving the DSN from the environment again would send them to
     * whatever DATABASE_URL/config/default.toml says — i.e. production —
     * while the run they are supervising lives somewhere else.
     */
    private static ?string $bootedDsn = null;

    /**
     * Accepts a plain libpq URL or a SQLAlchemy-style DSN
     * (`postgresql+asyncpg://…`) so the same config/default.toml value
     * works for both stacks.
     */
    public static function boot(?string $dsn = null): Capsule
    {
        if (self::$capsule !== null) {
            self::ensureGlobalBindings();

            return self::$capsule;
        }

        $resolved = $dsn ?? self::dsnFromEnv();
        self::$bootedDsn = $resolved;

        $container = new Container();
        $capsule = new Capsule($container);
        $capsule->addConnection(self::parseDsn($resolved));
        $capsule->setAsGlobal();
        $capsule->bootEloquent();

        $container->instance('db', $capsule->getDatabaseManager());

        self::$capsule = $capsule;
        self::$container = $container;
        self::ensureGlobalBindings();

        return $capsule;
    }

    /**
     * Re-assert the two pieces of global state Eloquent reads, so repositories
     * work identically standalone (crawler) and inside Laravel (dashboard):
     * the facade root behind `DB::`, and `Model::$resolver`.
     *
     * A live Laravel application is left alone — clobbering it would point the
     * dashboard's queries at this connection. "Live" has to be tested rather
     * than assumed. Once the library, the crawler and the dashboard became one
     * composer project their suites share a process, and a torn-down Laravel
     * app leaves both globals installed but dead: the facade root still
     * answers, and `Model::$resolver` is still Laravel's DatabaseManager
     * holding a flushed container. Every query in the crawler tests then died
     * on "Target class [config] does not exist". `bound('db')` is what
     * separates a booted application from a flushed one.
     */
    private static function ensureGlobalBindings(): void
    {
        if (self::$capsule === null || self::$container === null) {
            return;
        }

        $root = Facade::getFacadeApplication();
        if ($root !== null && $root->bound('db')) {
            return;
        }

        Facade::setFacadeApplication(self::$container);
        // setFacadeApplication() does not invalidate what the facades already
        // resolved, so `DB::` would keep answering with Laravel's
        // DatabaseManager — the one holding the flushed container.
        Facade::clearResolvedInstances();
        self::$capsule->setAsGlobal();
        // bootEloquent(), not setAsGlobal(): only this one re-points
        // Model::$resolver, the other global a Laravel teardown leaves
        // pointing at that same dead DatabaseManager.
        self::$capsule->bootEloquent();
    }

    /**
     * Resolved connection settings, without booting Eloquent.
     *
     * Public because the failsafe and watchdog paths open their OWN PDO
     * handle: they run when the shared connection may be broken, or inside
     * a forked child where inheriting a live handle would be unsafe.
     *
     * @return array<string, mixed>
     */
    public static function connectionConfig(?string $dsn = null): array
    {
        return self::parseDsn($dsn ?? self::$bootedDsn ?? self::dsnFromEnv());
    }

    /** The DSN boot() used, or null when boot() has not run. */
    public static function bootedDsn(): ?string
    {
        return self::$bootedDsn;
    }

    /** Test seam: drop the cached connection so a test can rebind. */
    public static function reset(): void
    {
        self::$capsule = null;
        self::$container = null;
        self::$bootedDsn = null;
    }

    private static function dsnFromEnv(): string
    {
        $dsn = getenv('DATABASE_URL');
        if (is_string($dsn) && $dsn !== '') {
            return $dsn;
        }

        $defaultToml = dirname(__DIR__, 2) . '/config/default.toml';
        if (is_file($defaultToml)) {
            $url = \PhpCollective\Toml\Toml::decodeFile($defaultToml)['database']['url'] ?? null;
            if (is_string($url) && $url !== '') {
                return $url;
            }
        }

        throw new RuntimeException(
            'No database URL: set DATABASE_URL or [database].url in config/default.toml'
        );
    }

    /** @return array<string, mixed> */
    private static function parseDsn(string $dsn): array
    {
        // Strip the SQLAlchemy driver suffix: postgresql+asyncpg -> postgresql
        $normalized = preg_replace('/^([a-z]+)\+[a-z0-9]+:/i', '$1:', $dsn) ?? $dsn;
        $parts = parse_url($normalized);
        if ($parts === false || !isset($parts['host'])) {
            throw new RuntimeException("Unparseable database URL: {$dsn}");
        }

        return [
            'driver' => 'pgsql',
            'host' => $parts['host'],
            'port' => $parts['port'] ?? 5432,
            'database' => ltrim($parts['path'] ?? '', '/'),
            'username' => isset($parts['user']) ? urldecode($parts['user']) : 'postgres',
            'password' => isset($parts['pass']) ? urldecode($parts['pass']) : '',
            'charset' => 'utf8',
            'prefix' => '',
            'schema' => 'public',
            'sslmode' => 'prefer',
        ];
    }
}
