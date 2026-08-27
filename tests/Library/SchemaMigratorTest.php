<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Schema\Migrator;
use PDO;
use PHPUnit\Framework\TestCase;
use RuntimeException;

/**
 * Covers what the schema gate cannot: the migrator's bookkeeping.
 *
 * The gate proves the baseline reproduces the schema. It says nothing about
 * whether applying twice applies twice, whether the ledger notices an edited
 * migration, or whether the migrator would run over a database Alembic still
 * owns — which is the one that matters most while both stacks are alive.
 *
 * Each test gets its own throwaway database on the TEST cluster, and drops it
 * again. Nothing here touches port 5432.
 */
final class SchemaMigratorTest extends TestCase
{
    private string $dbName = '';
    private string $dir = '';

    protected function setUp(): void
    {
        $this->dbName = 'bs_migrator_test_' . bin2hex(random_bytes(6));
        $this->admin()->exec('CREATE DATABASE "' . $this->dbName . '"');

        $this->dir = sys_get_temp_dir() . '/' . $this->dbName;
        mkdir($this->dir);
        file_put_contents(
            $this->dir . '/0001_first.sql',
            "CREATE TABLE public.widgets (id integer PRIMARY KEY);\n"
        );
    }

    protected function tearDown(): void
    {
        foreach ((array) glob($this->dir . '/*') as $f) {
            if (is_string($f)) {
                unlink($f);
            }
        }
        if (is_dir($this->dir)) {
            rmdir($this->dir);
        }
        $this->admin()->exec('DROP DATABASE IF EXISTS "' . $this->dbName . '" WITH (FORCE)');
    }

    public function test_apply_creates_the_objects_and_records_the_version(): void
    {
        $migrator = $this->migrator();

        self::assertSame(['0001_first'], $migrator->apply());
        self::assertSame([], $migrator->pending());
        self::assertArrayHasKey('0001_first', $migrator->applied());
        self::assertTrue($this->exists('widgets'));
    }

    public function test_applying_twice_applies_nothing_twice(): void
    {
        $this->migrator()->apply();

        // A second CREATE TABLE would throw, so an empty return is the whole
        // assertion: the ledger, not the SQL, is what stops it.
        self::assertSame([], $this->migrator()->apply());
    }

    public function test_a_second_migration_is_picked_up_in_order(): void
    {
        $this->migrator()->apply();
        file_put_contents(
            $this->dir . '/0002_second.sql',
            "ALTER TABLE public.widgets ADD COLUMN label text;\n"
        );

        self::assertSame(['0002_second'], $this->migrator()->apply());
    }

    public function test_editing_an_applied_migration_is_reported_as_drift(): void
    {
        $this->migrator()->apply();
        self::assertSame([], $this->migrator()->drift());

        file_put_contents(
            $this->dir . '/0001_first.sql',
            "CREATE TABLE public.widgets (id integer PRIMARY KEY, label text);\n"
        );

        self::assertSame(['0001_first'], $this->migrator()->drift());
    }

    /**
     * The guard that keeps this off production while Alembic still owns it.
     * A port number check would not do: the Python test database is stamped
     * too, and it is on the test cluster.
     */
    public function test_it_refuses_a_database_alembic_has_stamped(): void
    {
        $this->target()->exec('CREATE TABLE public.alembic_version (version_num varchar(32))');

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessageMatches('/Alembic owns its schema/');
        $this->migrator()->apply();
    }

    public function test_adopt_overrides_the_alembic_guard(): void
    {
        $this->target()->exec('CREATE TABLE public.alembic_version (version_num varchar(32))');

        self::assertSame(['0001_first'], $this->migrator()->apply(adopt: true));
    }

    public function test_a_failed_migration_leaves_no_ledger_row(): void
    {
        file_put_contents($this->dir . '/0002_broken.sql', "SELECT this_does_not_exist();\n");

        try {
            $this->migrator()->apply();
            self::fail('expected the broken migration to throw');
        } catch (RuntimeException $e) {
            self::assertStringContainsString('0002_broken', $e->getMessage());
        }

        // 0001 committed in its own transaction; 0002 left nothing behind.
        self::assertSame(['0001_first'], array_keys($this->migrator()->applied()));
    }

    public function test_a_misnamed_migration_file_is_rejected(): void
    {
        file_put_contents($this->dir . '/add_stuff.sql', "SELECT 1;\n");

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessageMatches('/NNNN_lower_snake/');
        $this->migrator()->available();
    }

    public function test_the_checked_in_baseline_is_the_only_shipped_migration(): void
    {
        $shipped = array_keys((new Migrator($this->target(), Migrator::defaultDir()))->available());

        self::assertSame(['0001_baseline'], $shipped);
    }

    private function migrator(): Migrator
    {
        return new Migrator($this->target(), $this->dir);
    }

    private function exists(string $table): bool
    {
        return (bool) $this->target()
            ->query("SELECT to_regclass('public.{$table}') IS NOT NULL")
            ->fetchColumn();
    }

    private function target(): PDO
    {
        return Migrator::connect(self::clusterDsn($this->dbName));
    }

    private function admin(): PDO
    {
        return Migrator::connect(self::clusterDsn('postgres'));
    }

    private static function clusterDsn(string $database): string
    {
        $base = getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test';

        return preg_replace('#/[^/]*$#', '/' . $database, $base) ?? $base;
    }
}
