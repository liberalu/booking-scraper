<?php

declare(strict_types=1);

namespace App\Schema;

use App\Support\Database;
use PDO;
use RuntimeException;

/**
 * Applies the plain-SQL migrations in `database/schema/` and records what it
 * applied.
 *
 * This is not `illuminate/database`'s migrator, on purpose. That one wants
 * PHP migration classes with `up()` / `down()` bodies built out of the
 * schema builder, and it needs `illuminate/filesystem` plus an event
 * dispatcher that are not currently installed. Migration 0001 is a 2,100-line
 * `pg_dump --schema-only`; re-expressing it as schema-builder calls is
 * exactly the 118-revision rewrite this baseline exists to avoid, and hand-
 * translating enums, partial unique indexes and CHECK expressions is where
 * a schema port loses fidelity. A file of SQL executed verbatim cannot drift
 * from the SQL it was dumped from.
 *
 * Alembic still owns the production catalogue. Nothing here runs against it:
 * `apply()` refuses a database that has an `alembic_version` table and no
 * ledger of its own.
 */
final class Migrator
{
    /**
     * PHP's one legitimately-owned table.
     *
     * Named for the stack rather than the tool (`migrations`, Laravel's
     * default, is the name most likely to be taken by something else later),
     * and created by the migrator rather than by migration 0001 — 0001 has
     * to stay a byte-faithful dump of the reference schema, so that the
     * schema gate can diff it without an exception list of its own.
     *
     * Always schema-qualified: migration 0001 ends with the search_path
     * pg_dump sets, which is the empty string.
     */
    public const LEDGER = 'public.php_schema_migrations';

    public function __construct(
        private readonly PDO $pdo,
        private readonly string $dir,
    ) {
        if (!is_dir($this->dir)) {
            throw new RuntimeException("No migrations directory: {$this->dir}");
        }
    }

    /**
     * Default location: `database/schema/`, which is where Laravel itself
     * puts a dumped SQL schema (`artisan schema:dump`) — not
     * `database/migrations/`, whose contents `artisan migrate` would run.
     * Running this baseline that way is the one thing that must not happen:
     * see the note in that directory.
     */
    public static function defaultDir(): string
    {
        return dirname(__DIR__, 2) . '/database/schema';
    }

    /**
     * A PDO handle for an explicit DSN.
     *
     * Explicit only — there is deliberately no fallback to
     * `config/default.toml`, whose `[database].url` is production.
     */
    public static function connect(string $dsn): PDO
    {
        $c = Database::connectionConfig($dsn);

        return new PDO(
            sprintf('pgsql:host=%s;port=%s;dbname=%s', $c['host'], $c['port'], $c['database']),
            (string) $c['username'],
            (string) $c['password'],
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION],
        );
    }

    /** True when Alembic has stamped this database. */
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
            'CREATE TABLE IF NOT EXISTS ' . self::LEDGER . ' ('
            . ' version text PRIMARY KEY,'
            . ' checksum text NOT NULL,'
            . ' applied_at timestamptz NOT NULL DEFAULT now()'
            . ')'
        );
    }

    /**
     * Migrations on disk, in application order.
     *
     * @return array<string, string> version => absolute path
     */
    public function available(): array
    {
        $found = [];
        foreach ((array) glob($this->dir . '/*.sql') as $path) {
            if (!is_string($path)) {
                continue;
            }
            $name = basename($path, '.sql');
            if (preg_match('/^\d{4}_[a-z0-9_]+$/', $name) !== 1) {
                throw new RuntimeException(
                    "Migration filename must be NNNN_lower_snake.sql, got: " . basename($path)
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
        if (!$this->ledgerExists()) {
            return [];
        }

        $rows = $this->pdo
            ->query('SELECT version, checksum, applied_at FROM ' . self::LEDGER . ' ORDER BY version')
            ->fetchAll(PDO::FETCH_ASSOC);

        $out = [];
        foreach ($rows as $row) {
            $out[(string) $row['version']] = [
                'checksum' => (string) $row['checksum'],
                'applied_at' => (string) $row['applied_at'],
            ];
        }

        return $out;
    }

    /** @return array<string, string> version => path */
    public function pending(): array
    {
        return array_diff_key($this->available(), $this->applied());
    }

    /**
     * Applied migrations whose file has changed since it was applied.
     *
     * A migration is a record of what was done to a database, so editing an
     * applied one means the ledger is lying about what the database contains.
     *
     * @return list<string>
     */
    public function drift(): array
    {
        $drifted = [];
        $available = $this->available();
        foreach ($this->applied() as $version => $row) {
            if (!isset($available[$version])) {
                continue;
            }
            if (self::checksum($available[$version]) !== $row['checksum']) {
                $drifted[] = $version;
            }
        }

        return $drifted;
    }

    /**
     * Apply everything pending. Each migration is one transaction — Postgres
     * DDL is transactional, so a migration that fails half way leaves
     * nothing behind and no ledger row.
     *
     * @return list<string> versions applied, in order
     */
    public function apply(bool $adopt = false): array
    {
        if (!$adopt && $this->alembicOwned() && !$this->ledgerExists()) {
            throw new RuntimeException(
                'Refusing to migrate: this database has an alembic_version table and no '
                . 'PHP ledger, so Alembic owns its schema. Transferring ownership of an '
                . 'existing catalogue is a separate, deliberate step — pass --adopt to do '
                . 'it anyway.'
            );
        }

        $this->ensureLedger();

        $done = [];
        foreach ($this->pending() as $version => $path) {
            $sql = file_get_contents($path);
            if ($sql === false) {
                throw new RuntimeException("Unreadable migration: {$path}");
            }

            $this->pdo->beginTransaction();
            try {
                // One PQexec for the whole file: no statement splitting, so
                // nothing to get wrong around dollar-quoting or semicolons
                // inside string literals.
                $this->pdo->exec($sql);
                $stmt = $this->pdo->prepare(
                    'INSERT INTO ' . self::LEDGER . ' (version, checksum) VALUES (?, ?)'
                );
                $stmt->execute([$version, self::checksum($path)]);
                $this->pdo->commit();
            } catch (\Throwable $e) {
                $this->pdo->rollBack();
                throw new RuntimeException("Migration {$version} failed: " . $e->getMessage(), 0, $e);
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

        return 'sha256:' . $hash;
    }

    private function tableExists(string $name): bool
    {
        $stmt = $this->pdo->prepare(
            "SELECT to_regclass('public.' || ?) IS NOT NULL"
        );
        $stmt->execute([$name]);

        return (bool) $stmt->fetchColumn();
    }
}
