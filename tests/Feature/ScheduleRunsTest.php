<?php

declare(strict_types=1);

namespace Tests\Feature;

use App\Repositories\SchedulerRepository;
use Illuminate\Support\Facades\DB;
use PDO;
use PHPUnit\Framework\Attributes\Group;
use Tests\Support\FixtureDatabase;
use Tests\Support\SyntheticShop;
use Tests\TestCase;
use Tests\UsesTestDatabase;

final class ScheduleRunsTest extends TestCase
{
    use UsesTestDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        $this->useTestDatabase(FixtureDatabase::ensure(
            getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test',
            recreate: true
        ));
    }

    private function plantJob(string $shopName): int
    {
        DB::table('cron_jobs')->delete();
        $shopId = (int) DB::table('shops')->where('name', $shopName)->value('id');

        return (int) DB::selectOne(
            "insert into cron_jobs (shop_id, phase, strategy, args, cron_expression,
                 enabled, created_at)
             values (?, 'discover', 'sitemap', '', '* * * * *', true, now())
             returning id",
            [$shopId]
        )->id;
    }

    #[Group('db')]
    public function test_a_due_job_on_an_idle_shop_is_reported(): void
    {
        DB::beginTransaction();
        try {

            $id = $this->plantJob(SyntheticShop::SHOP_TWO);

            $this->artisan('runs:schedule --dry-run')
                ->expectsOutputToContain("cron job #{$id} due")
                ->assertExitCode(0);
        } finally {
            DB::rollBack();
        }
    }

    #[Group('db')]
    public function test_a_running_crawl_holds_back_that_shop(): void
    {
        DB::beginTransaction();
        try {

            $id = $this->plantJob(SyntheticShop::SHOP_TWO);
            DB::insert(
                "insert into scrape_runs (shop_id, phase, status, started_at, last_heartbeat,
                     urls_processed, items_added, items_updated, errors_4xx, errors_5xx,
                     error_count)
                 select shop_id, 'scan', 'running', now(), now(), 0, 0, 0, 0, 0, 0
                   from cron_jobs where id = ?",
                [$id]
            );

            $this->artisan('runs:schedule --dry-run')
                ->expectsOutputToContain("skipping cron job #{$id}")
                ->assertExitCode(0);
        } finally {
            DB::rollBack();
        }
    }

    #[Group('db')]
    public function test_a_paused_run_holds_a_shop_back(): void
    {

        DB::beginTransaction();
        try {
            $shopId = (int) DB::table('shops')->where('name', SyntheticShop::SHOP_TWO)->value('id');
            DB::insert(
                "insert into scrape_runs (shop_id, phase, status, started_at, urls_processed,
                     items_added, items_updated, errors_4xx, errors_5xx, error_count)
                 values (?, 'scan', 'paused', now() - make_interval(days => 100), 0, 0, 0, 0, 0, 0)",
                [$shopId]
            );
            $id = $this->plantJob(SyntheticShop::SHOP_TWO);

            $this->artisan('runs:schedule --dry-run')
                ->expectsOutputToContain("skipping cron job #{$id}")
                ->assertExitCode(0);
        } finally {
            DB::rollBack();
        }
    }

    #[Group('db')]
    public function test_a_disabled_job_is_not_reported(): void
    {
        DB::beginTransaction();
        try {
            $id = $this->plantJob(SyntheticShop::SHOP_TWO);
            DB::table('cron_jobs')->where('id', $id)->update(['enabled' => false]);

            $this->artisan('runs:schedule --dry-run')
                ->doesntExpectOutputToContain("cron job #{$id}")
                ->assertExitCode(0);
        } finally {
            DB::rollBack();
        }
    }

    #[Group('db')]
    public function test_max_per_tick_defers_the_rest(): void
    {
        DB::beginTransaction();
        try {
            $first = $this->plantJob(SyntheticShop::SHOP_TWO);

            $second = (int) DB::selectOne(
                "insert into cron_jobs (shop_id, phase, strategy, args, cron_expression,
                     enabled, created_at)
                 select shop_id, 'discover', 'sitemap', '', '* * * * *', true, now()
                   from cron_jobs where id = ? returning id",
                [$first]
            )->id;

            $this->artisan('runs:schedule --dry-run --max-per-tick=1')
                ->expectsOutputToContain("cron job #{$first} due")
                ->expectsOutputToContain("deferring cron job #{$second}")
                ->assertExitCode(0);
        } finally {
            DB::rollBack();
        }
    }

    #[Group('db')]
    public function test_a_second_scheduler_cannot_claim_the_same_shop(): void
    {
        DB::beginTransaction();
        $connection = null;
        try {
            $id = $this->plantJob(SyntheticShop::SHOP_TWO);
            $shopId = (int) DB::table('cron_jobs')->where('id', $id)->value('shop_id');
            $connection = $this->separateConnection();
            $statement = $connection->prepare(
                'select pg_advisory_lock(7351, cast(? as integer))',
            );
            $statement->execute([$shopId]);

            self::assertFalse((new SchedulerRepository)->tryAcquireShop($shopId));
        } finally {
            if ($connection instanceof PDO) {
                $connection->exec('select pg_advisory_unlock_all()');
            }
            DB::rollBack();
        }
    }

    private function separateConnection(): PDO
    {
        $dsn = sprintf(
            'pgsql:host=%s;port=%d;dbname=%s',
            config('database.connections.pgsql.host'),
            config('database.connections.pgsql.port'),
            config('database.connections.pgsql.database'),
        );

        return new PDO(
            $dsn,
            config('database.connections.pgsql.username'),
            config('database.connections.pgsql.password'),
            [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            ],
        );
    }
}
