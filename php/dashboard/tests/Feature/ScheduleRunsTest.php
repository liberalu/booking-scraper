<?php

declare(strict_types=1);

namespace Tests\Feature;

use BookScraper\Testing\FixtureDatabase;
use BookScraper\Testing\SyntheticShop;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use Tests\TestCase;
use Tests\UsesTestDatabase;

/**
 * The scheduler's plumbing and its concurrency policy.
 *
 * CronScheduleTest covers which windows are due; this covers the part that
 * needs a database — whether an in-flight run for the shop holds a job back —
 * and the fact that the command loads and reports at all.
 *
 * Every case runs `--dry-run`, so nothing is ever spawned.
 */
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

    /**
     * A job due every minute, so due-ness is never the variable under test.
     *
     * Clears the table first: the fixture plants a cron job of its own, and it
     * competes for the max-per-tick budget and for the shop's idle slot. Every
     * caller is inside a transaction that rolls back.
     */
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
            // synthetic-two has no runs at all.
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
            // Planted here rather than taken from the fixture: the fixture has
            // no `running` run (its frozen /api/runs?status=running shape is an
            // empty list), and it cannot gain one — the goldens were frozen
            // against it while Python still existed, and nothing can re-freeze
            // them now.
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
    public function test_a_paused_run_does_not_hold_a_shop_back(): void
    {
        // Deliberate, and the opposite of the crawler's own preflight. A paused
        // run is parked by an operator and the reaper leaves it alone by design,
        // so it can sit for months — there is one on patogupirkti from May.
        // Counting it as busy would stop that shop's schedules permanently.
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
                ->expectsOutputToContain("cron job #{$id} due")
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
            // Not plantJob() again — that clears the table.
            $second = (int) DB::selectOne(
                "insert into cron_jobs (shop_id, phase, strategy, args, cron_expression,
                     enabled, created_at)
                 select shop_id, 'discover', 'sitemap', '', '* * * * *', true, now()
                   from cron_jobs where id = ? returning id",
                [$first]
            )->id;

            // Both are due; one fires, and the other says so rather than
            // vanishing — twelve crawls starting at once is the thing being
            // avoided, and silence would hide it.
            $this->artisan('runs:schedule --dry-run --max-per-tick=1')
                ->expectsOutputToContain("cron job #{$first} due")
                ->expectsOutputToContain("deferring cron job #{$second}")
                ->assertExitCode(0);
        } finally {
            DB::rollBack();
        }
    }
}
