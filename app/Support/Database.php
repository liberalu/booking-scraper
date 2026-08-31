<?php

declare(strict_types=1);

namespace App\Support;

use Illuminate\Database\Capsule\Manager as Capsule;
use Illuminate\Database\DatabaseManager;
use Illuminate\Foundation\Application;
use Illuminate\Support\Facades\Facade;
use PhpCollective\Toml\Toml;
use RuntimeException;

final class Database
{
    private static ?Capsule $capsule = null;

    private static ?Application $container = null;

    private static ?string $bootedDsn = null;

    public static function boot(?string $dsn = null): Capsule
    {
        $booted = self::$capsule;
        if ($booted !== null) {
            self::ensureGlobalBindings();

            return $booted;
        }

        $resolved = $dsn ?? self::dsnFromEnv();
        self::$bootedDsn = $resolved;

        $container = new Application(dirname(__DIR__, 2));
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

        Facade::clearResolvedInstances();
        self::$capsule->setAsGlobal();

        self::$capsule->bootEloquent();
    }

    /**
     * @return array{driver: 'pgsql', host: string, port: int, database: string, username: string, password: string, charset: 'utf8', prefix: '', schema: 'public', sslmode: 'prefer'}
     */
    public static function connectionConfig(?string $dsn = null): array
    {
        return self::parseDsn($dsn ?? self::$bootedDsn ?? self::dsnFromEnv());
    }

    public static function manager(): DatabaseManager
    {
        return (self::$capsule ?? self::boot())->getDatabaseManager();
    }

    public static function bootedDsn(): ?string
    {
        return self::$bootedDsn;
    }

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

        $defaultToml = dirname(__DIR__, 2).'/config/default.toml';
        if (is_file($defaultToml)) {
            $decoded = Toml::decodeFile($defaultToml);
            $database = $decoded['database'] ?? null;
            if (is_array($database)) {
                $url = $database['url'] ?? null;
                if (is_string($url) && $url !== '') {
                    return $url;
                }
            }
        }

        throw new RuntimeException(
            'No database URL: set DATABASE_URL or [database].url in config/default.toml'
        );
    }

    /**
     * @return array{driver: 'pgsql', host: string, port: int, database: string, username: string, password: string, charset: 'utf8', prefix: '', schema: 'public', sslmode: 'prefer'}
     */
    private static function parseDsn(string $dsn): array
    {

        $normalized = preg_replace('/^([a-z]+)\+[a-z0-9]+:/i', '$1:', $dsn) ?? $dsn;
        $parts = parse_url($normalized);
        if ($parts === false || ! isset($parts['host'])) {
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
