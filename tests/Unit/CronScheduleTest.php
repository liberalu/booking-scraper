<?php

declare(strict_types=1);

namespace Tests\Unit;

use App\Models\CronJob;
use App\Support\CronSchedule;
use DateTimeImmutable;
use DateTimeZone;
use Illuminate\Support\Carbon;
use Tests\TestCase;

final class CronScheduleTest extends TestCase
{
    private static function job(
        int $id,
        string $expression,
        ?string $lastRun = null,
        bool $enabled = true,
        string $phase = 'discover',
        ?string $strategy = 'sitemap',
        string $args = ''
    ): CronJob {
        $job = new CronJob;
        $job->id = $id;
        $job->shop_id = 1;
        $job->phase = $phase;
        $job->strategy = $strategy;
        $job->cron_expression = $expression;
        $job->enabled = $enabled;
        $job->args = $args;
        $job->last_run_at = $lastRun === null ? null : Carbon::parse($lastRun);

        return $job;
    }

    private static function at(string $utc): DateTimeImmutable
    {
        return new DateTimeImmutable($utc, new DateTimeZone('UTC'));
    }

    public function test_a_job_never_run_is_due(): void
    {
        $due = CronSchedule::due([self::job(1, '0 2 * * *')], self::at('2026-08-26 02:00:05'));

        self::assertCount(1, $due);
        self::assertSame('2026-08-26 02:00:00', $due[0]['due']->format('Y-m-d H:i:s'));
    }

    public function test_a_job_already_run_for_this_window_is_not_due(): void
    {
        $job = self::job(1, '0 2 * * *', lastRun: '2026-08-26 02:00:03');

        self::assertSame([], CronSchedule::due([$job], self::at('2026-08-26 02:30:00')));
    }

    public function test_the_next_window_is_due_again(): void
    {

        $job = self::job(1, '0 2 * * *', lastRun: '2026-08-25 02:00:03');

        self::assertCount(1, CronSchedule::due([$job], self::at('2026-08-26 02:00:01')));
    }

    public function test_a_disabled_job_is_never_due(): void
    {
        $job = self::job(1, '0 2 * * *', enabled: false);

        self::assertSame([], CronSchedule::due([$job], self::at('2026-08-26 02:00:05')));
    }

    public function test_a_window_that_has_not_arrived_yet_is_not_due(): void
    {

        $job = self::job(1, '30 5 * * 0', lastRun: '2026-08-23 05:30:02');

        self::assertSame([], CronSchedule::due([$job], self::at('2026-08-26 09:00:00')));
    }

    public function test_a_missed_window_still_fires_late(): void
    {

        $job = self::job(1, '0 2 * * *', lastRun: '2026-08-25 02:00:02');

        $due = CronSchedule::due([$job], self::at('2026-08-26 09:00:00'));

        self::assertCount(1, $due);
        self::assertSame('2026-08-26 02:00:00', $due[0]['due']->format('Y-m-d H:i:s'));
    }

    public function test_a_job_already_fired_by_this_process_is_not_fired_again(): void
    {

        $job = self::job(1, '0 2 * * *');
        $windowStart = self::at('2026-08-26 02:00:00')->getTimestamp();

        self::assertSame([], CronSchedule::due([$job], self::at('2026-08-26 02:00:30'), [1 => $windowStart]));
    }

    public function test_being_fired_for_an_earlier_window_does_not_block_a_later_one(): void
    {
        $job = self::job(1, '0 2 * * *');
        $yesterday = self::at('2026-08-25 02:00:00')->getTimestamp();

        self::assertCount(
            1,
            CronSchedule::due([$job], self::at('2026-08-26 02:00:30'), [1 => $yesterday])
        );
    }

    public function test_a_broken_expression_is_skipped_not_thrown(): void
    {

        $jobs = [self::job(1, 'not a cron line'), self::job(2, '0 2 * * *')];

        $due = CronSchedule::due($jobs, self::at('2026-08-26 02:00:05'));

        self::assertCount(1, $due);
        self::assertSame(2, $due[0]['job']->id);
    }

    public function test_the_oldest_due_window_comes_first(): void
    {

        $jobs = [
            self::job(1, '0 8 * * *'),
            self::job(2, '0 2 * * *'),
            self::job(3, '0 5 * * *'),
        ];

        $due = CronSchedule::due($jobs, self::at('2026-08-26 09:00:00'));

        self::assertSame([2, 3, 1], array_map(static fn (array $d): int => $d['job']->id, $due));
    }

    public function test_rescrape_true_becomes_a_full_scan(): void
    {

        $job = self::job(2, '0 1 2,16 * *', phase: 'scan', strategy: null, args: '-a rescrape=true');

        $due = CronSchedule::due([$job], self::at('2026-09-02 01:00:05'));

        self::assertCount(1, $due);
        self::assertSame('full', $due[0]['mode']);
        self::assertSame([], $due[0]['unknownArgs']);
    }

    public function test_no_args_means_a_delta_scan(): void
    {
        $job = self::job(2, '0 3 * * *', phase: 'scan', strategy: 'delta');

        $due = CronSchedule::due([$job], self::at('2026-08-26 03:00:05'));

        self::assertSame('delta', $due[0]['mode']);
    }

    public function test_an_unrecognised_arg_is_reported_rather_than_dropped(): void
    {

        $job = self::job(2, '0 3 * * *', phase: 'scan', args: '-a max_urls=20 -a rescrape=true');

        $due = CronSchedule::due([$job], self::at('2026-08-26 03:00:05'));

        self::assertSame('full', $due[0]['mode']);
        self::assertSame(['max_urls=20'], $due[0]['unknownArgs']);
    }

    public function test_expressions_are_read_as_utc(): void
    {

        $due = CronSchedule::previousDue('0 2 * * *', self::at('2026-08-26 02:30:00'));

        self::assertNotNull($due);
        self::assertSame('2026-08-26 02:00:00 UTC', $due->format('Y-m-d H:i:s T'));
    }

    public function test_a_local_clock_is_converted_before_matching(): void
    {

        $vilnius = new DateTimeImmutable('2026-08-26 04:30:00', new DateTimeZone('Europe/Vilnius'));

        $due = CronSchedule::previousDue('0 2 * * *', $vilnius);

        self::assertNotNull($due);
        self::assertSame('2026-08-25 02:00:00', $due->format('Y-m-d H:i:s'));
    }
}
