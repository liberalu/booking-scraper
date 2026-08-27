<?php

declare(strict_types=1);

namespace App\Support;

use App\Models\CronJob;
use Cron\CronExpression;
use DateTimeImmutable;
use DateTimeZone;

/**
 * Decides which scheduled jobs are due, and how to run them.
 *
 * Kept apart from the command so the decision is testable without spawning
 * anything: everything here is a pure function of the jobs, the clock, and
 * what this process has already fired.
 *
 * Replaces scripts/generate_crontab.py, which rendered one crontab line per
 * enabled job and installed it at container boot. Two reasons this is a poll
 * loop instead of a crontab:
 *
 *  - There is no container any more. The crawler runs from the CLI, and
 *    writing to a host's crontab from an application is a worse idea than
 *    owning a process.
 *  - The crontab only picked up edits at boot, so a schedule created in the
 *    dashboard did nothing until someone restarted the scraper. A loop reads
 *    the table every tick, which is what the dashboard's Schedules page has
 *    always implied.
 *
 * **Expressions are UTC.** The container's cron was too — job 1 is `0 2 * * *`
 * and its runs start at 02:00 UTC — so this preserves the times that are
 * already in the table rather than silently shifting every schedule by
 * Vilnius's offset.
 */
final class CronSchedule
{
    /**
     * Python's `-a key=value` extras, mapped to this crawler's flags.
     *
     * `cron_jobs.args` was appended raw to a `scrapy crawl` line, so what is
     * in the column is Python's argument syntax. Only one value is actually in
     * use — `rescrape=true` on the twice-monthly full scans — and anything
     * unrecognised is reported rather than dropped: quietly discarding a
     * scheduled job's argument changes what the crawl does.
     */
    private const ARG_TRANSLATIONS = [
        'rescrape=true' => ['mode' => 'full'],
        'rescrape=false' => ['mode' => 'delta'],
    ];

    /**
     * The jobs whose most recent due time has not been run yet.
     *
     * @param iterable<CronJob> $jobs
     * @param array<int, int> $firedAt  job id => due timestamp this process already fired
     * @return list<array{job: CronJob, due: DateTimeImmutable, mode: string, unknownArgs: list<string>}>
     */
    public static function due(
        iterable $jobs,
        DateTimeImmutable $now,
        array $firedAt = []
    ): array {
        $out = [];

        foreach ($jobs as $job) {
            if (! $job->enabled) {
                continue;
            }
            $due = self::previousDue($job->cron_expression, $now);
            if ($due === null) {
                continue;
            }

            // Already run: last_run_at is at or after this due time.
            //
            // Note what that column means — RunLifecycle stamps it on EVERY
            // cron job for the shop+phase a run belongs to, not just the one
            // that triggered it. So a manual scan of vaga suppresses vaga's
            // next scheduled scan window, which is the behaviour worth having
            // (don't scan the same shop twice within the hour) but is not the
            // same as "this job ran".
            $lastRun = $job->last_run_at?->toDateTimeImmutable();
            if ($lastRun !== null && $lastRun >= $due) {
                continue;
            }

            // Already fired by this process. Belt to the DB's braces: if a
            // spawn fails, or the crawl dies before stamping last_run_at,
            // nothing else stops this job being fired again every tick.
            if (($firedAt[$job->id] ?? null) === $due->getTimestamp()) {
                continue;
            }

            $translated = self::translateArgs((string) ($job->args ?? ''));
            $out[] = [
                'job' => $job,
                'due' => $due,
                'mode' => $translated['mode'] ?? 'delta',
                'unknownArgs' => $translated['unknown'],
            ];
        }

        // Oldest due time first, so a backlog drains in the order it built up.
        usort($out, static fn (array $a, array $b): int => $a['due'] <=> $b['due']);

        return $out;
    }

    /**
     * The most recent time this expression was due, at or before `$now`.
     * Null if the expression does not parse — a job with a broken expression
     * is skipped rather than crashing the loop, since one bad row would
     * otherwise stop every other schedule.
     */
    public static function previousDue(string $expression, DateTimeImmutable $now): ?DateTimeImmutable
    {
        if (! CronExpression::isValidExpression($expression)) {
            return null;
        }

        $utc = $now->setTimezone(new DateTimeZone('UTC'));
        $previous = (new CronExpression($expression))
            ->getPreviousRunDate($utc, 0, allowCurrentDate: true);

        return DateTimeImmutable::createFromInterface($previous)
            ->setTimezone(new DateTimeZone('UTC'));
    }

    /**
     * @return array{mode?: string, unknown: list<string>}
     */
    public static function translateArgs(string $args): array
    {
        $out = ['unknown' => []];
        foreach (preg_split('/\s+/', trim($args), -1, PREG_SPLIT_NO_EMPTY) ?: [] as $token) {
            // `-a key=value`: the `-a` separators carry no meaning here.
            if ($token === '-a') {
                continue;
            }
            if (isset(self::ARG_TRANSLATIONS[$token])) {
                $out = array_merge($out, self::ARG_TRANSLATIONS[$token]);
                continue;
            }
            $out['unknown'][] = $token;
        }

        return $out;
    }
}
