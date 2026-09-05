<?php

declare(strict_types=1);

namespace App\Schema;

use App\Support\Database;
use PDO;
use RuntimeException;
use Throwable;

final readonly class Migrator
{
    public const string LEDGER = 'public.php_schema_migrations';

    public function __construct(
        private PDO $pdo,
        private string $dir,
    ) {
        if (! is_dir($this->dir)) {
            throw new RuntimeException("No migrations directory: {$this->dir}");
        }
    }

    public static function defaultDir(): string
    {
        return dirname(__DIR__, 2).'/database/schema';
    }

    public static function connect(string $dsn): PDO
    {
        $c = Database::connectionConfig($dsn);

        return new PDO(
            sprintf('pgsql:host=%s;port=%s;dbname=%s', $c['host'], $c['port'], $c['database']),
            $c['username'],
            $c['password'],
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION],
        );
    }

    public function alembicOwned(): bool
    {
        return $this->tableExists('alembic_version');
    }

    public function ledgerExists(): bool
    {
        return $this->tableExists('php_schema_migrations');
    }

    public function ensureLedger(): void
    {
        $this->pdo->exec(
            'CREATE TABLE IF NOT EXISTS '.self::LEDGER.' ('
            .' version text PRIMARY KEY,'
            .' checksum text NOT NULL,'
            .' applied_at timestamptz NOT NULL DEFAULT now()'
            .')'
        );
    }

    /** @return array<string, string> */
    public function available(): array
    {
        $found = [];
        $paths = glob($this->dir.'/*.sql');
        foreach ($paths !== false ? $paths : [] as $path) {
            $name = basename($path, '.sql');
            if (preg_match('/^\d{4}_[a-z0-9_]+$/', $name) !== 1) {
                throw new RuntimeException(
                    'Migration filename must be NNNN_lower_snake.sql, got: '.basename($path)
                );
            }
            $found[$name] = $path;
        }
        ksort($found, SORT_STRING);

        return $found;
    }

    /** @return array<string, array{checksum: string, applied_at: string}> */
    public function applied(): array
    {
        if (! $this->ledgerExists()) {
            return [];
        }

        $statement = $this->pdo
            ->query('SELECT version, checksum, applied_at FROM '.self::LEDGER.' ORDER BY version');
        if ($statement === false) {
            throw new RuntimeException('Could not read the migration ledger.');
        }
        $rows = $statement->fetchAll(PDO::FETCH_ASSOC);

        $out = [];
        foreach ($rows as $row) {
            if (! is_array($row)
                || ! is_string($row['version'] ?? null)
                || ! is_string($row['checksum'] ?? null)
                || ! is_string($row['applied_at'] ?? null)) {
                throw new RuntimeException('The migration ledger contains an invalid row.');
            }
            $out[$row['version']] = [
                'checksum' => $row['checksum'],
                'applied_at' => $row['applied_at'],
            ];
        }

        return $out;
    }

    /** @return array<string, string> */
    public function pending(): array
    {
        return array_diff_key($this->available(), $this->applied());
    }

    /** @return list<string> */
    public function drift(): array
    {
        $drifted = [];
        $available = $this->available();
        foreach ($this->applied() as $version => $row) {
            if (! isset($available[$version])) {
                continue;
            }
            if (self::checksum($available[$version]) !== $row['checksum']) {
                $drifted[] = $version;
            }
        }

        return $drifted;
    }

    /** @return list<string> */
    public function apply(bool $adopt = false): array
    {
        $alembicOwned = $this->alembicOwned();
        $hadLedger = $this->ledgerExists();
        if (! $adopt && $alembicOwned && ! $hadLedger) {
            throw new RuntimeException(
                'Refusing to migrate: this database has an alembic_version table and no '
                .'PHP ledger, so Alembic owns its schema. Transferring ownership of an '
                .'existing catalogue is a separate, deliberate step — pass --adopt to do '
                .'it anyway.'
            );
        }

        $this->ensureLedger();
        if ($adopt && $alembicOwned && ! $hadLedger) {
            $this->adoptExistingBaseline();
        }

        $done = [];
        foreach ($this->pending() as $version => $path) {
            $sql = file_get_contents($path);
            if ($sql === false) {
                throw new RuntimeException("Unreadable migration: {$path}");
            }

            $this->pdo->beginTransaction();
            try {

                $this->pdo->exec($sql);
                $stmt = $this->pdo->prepare(
                    'INSERT INTO '.self::LEDGER.' (version, checksum) VALUES (?, ?)'
                );
                $stmt->execute([$version, self::checksum($path)]);
                $this->pdo->commit();
            } catch (Throwable $e) {
                $this->pdo->rollBack();
                throw new RuntimeException("Migration {$version} failed: ".$e->getMessage(), 0, $e);
            }

            $done[] = $version;
        }

        return $done;
    }

    public static function checksum(string $path): string
    {
        $hash = hash_file('sha256', $path);
        if ($hash === false) {
            throw new RuntimeException("Cannot checksum: {$path}");
        }

        return 'sha256:'.$hash;
    }

    private function tableExists(string $name): bool
    {
        $stmt = $this->pdo->prepare(
            "SELECT to_regclass('public.' || ?) IS NOT NULL"
        );
        $stmt->execute([$name]);

        return (bool) $stmt->fetchColumn();
    }

    private function adoptExistingBaseline(): void
    {
        $baseline = $this->available()['0001_baseline'] ?? null;
        if ($baseline === null || ! $this->tableExists('scrape_runs')) {
            return;
        }

        $statement = $this->pdo->prepare(
            'INSERT INTO '.self::LEDGER.' (version, checksum) VALUES (?, ?) '
            .'ON CONFLICT (version) DO NOTHING'
        );
        $statement->execute(['0001_baseline', self::checksum($baseline)]);
    }
}
