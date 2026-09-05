<?php

declare(strict_types=1);

namespace App\Support;

use App\Models\CronJob;
use Cron\CronExpression;
use DateTimeImmutable;
use DateTimeZone;

final class CronSchedule
{
    private const array ARG_TRANSLATIONS = [
        'rescrape=true' => ['mode' => 'full'],
        'rescrape=false' => ['mode' => 'delta'],
    ];

    /**
     * @param  iterable<CronJob>  $jobs
     * @param  array<int, int>  $firedAt
     * @return list<array{job: CronJob, due: DateTimeImmutable, mode: string, unknownArgs: list<string>}>
     */
    public static function due(
        iterable $jobs,
        DateTimeImmutable $now,
        array $firedAt = []
    ): array {
        $out = [];

        foreach ($jobs as $job) {
            if ($job->enabled === false) {
                continue;
            }
            $due = self::previousDue($job->cron_expression, $now);
            if (! $due instanceof DateTimeImmutable) {
                continue;
            }

            $lastRun = $job->last_run_at?->toDateTimeImmutable();
            if ($lastRun !== null && $lastRun >= $due) {
                continue;
            }

            if (($firedAt[$job->id] ?? null) === $due->getTimestamp()) {
                continue;
            }

            $translated = self::translateArgs($job->args ?? '');
            $out[] = [
                'job' => $job,
                'due' => $due,
                'mode' => $translated['mode'] ?? 'delta',
                'unknownArgs' => $translated['unknown'],
            ];
        }

        usort(
            $out,
            static fn (array $a, array $b): int => $a['due'] <=> $b['due'],
        );

        return $out;
    }

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

    /** @return array{unknown: list<string>, mode?: string} */
    public static function translateArgs(string $args): array
    {
        $out = ['unknown' => []];
        $tokens = preg_split('/\s+/', trim($args), -1, PREG_SPLIT_NO_EMPTY);
        foreach ($tokens !== false ? $tokens : [] as $token) {

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
