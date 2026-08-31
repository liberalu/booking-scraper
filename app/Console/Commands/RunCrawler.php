<?php

declare(strict_types=1);

namespace App\Console\Commands;

use Illuminate\Console\Command;
use Symfony\Component\Process\Process;

final class RunCrawler extends Command
{
    protected $signature = 'crawler:run
        {phase : discover, scan or reconcile}
        {--shop=}
        {--strategy=}
        {--mode=}
        {--urls=}
        {--max-urls=}
        {--max-pages=}
        {--max-bands=}
        {--database=}
        {--cron-job-id=}
        {--resumed-attempt=}
        {--adopt-run-id=}
        {--dry-run}';

    protected $description = 'Run a crawler phase';

    public function handle(): int
    {
        $phase = $this->argument('phase');
        if (! in_array($phase, ['discover', 'scan', 'reconcile'], true)) {
            $this->error('phase must be discover, scan or reconcile');

            return self::INVALID;
        }

        $command = [PHP_BINARY, base_path('bin/crawl'), $phase];
        foreach ([
            'shop',
            'strategy',
            'mode',
            'urls',
            'max-urls',
            'max-pages',
            'max-bands',
            'database',
            'cron-job-id',
            'resumed-attempt',
            'adopt-run-id',
        ] as $name) {
            $value = $this->option($name);
            if (is_string($value) && $value !== '') {
                $command[] = "--{$name}={$value}";
            }
        }
        if ($this->option('dry-run')) {
            $command[] = '--dry-run';
        }

        $process = new Process($command, base_path(), null, null, null);

        return $process->run(function (string $type, string $output): void {
            $type === Process::ERR
                ? $this->output->write($output, false, 1)
                : $this->output->write($output, false);
        });
    }
}
