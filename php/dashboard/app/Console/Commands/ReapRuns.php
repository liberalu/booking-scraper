<?php

declare(strict_types=1);

namespace App\Console\Commands;

use BookScraper\Runs\Reaper;
use Illuminate\Console\Command;

/**
 * Fails runs whose process died.
 *
 * The Python dashboard runs this on an asyncio timer inside its own process.
 * PHP has no equivalent event loop, and putting it on the read path was
 * rejected on purpose: this dashboard's GET endpoints are read-only, and a
 * sweep triggered by whoever happens to load the runs page makes a write
 * depend on browsing. So it is a command — run it under a supervisor, a cron
 * entry, or `--watch`.
 *
 * Without something running it, a crawl that dies without unwinding leaves
 * its row `running` forever: the runs list shows it live, and the shop+phase
 * preflight refuses to start a replacement.
 */
final class ReapRuns extends Command
{
    protected $signature = 'runs:reap
        {--watch : keep sweeping instead of exiting after one pass}
        {--interval=30 : seconds between sweeps in --watch mode}';

    protected $description = 'Fail runs whose heartbeat has gone stale';

    public function handle(): int
    {
        $interval = max(5, (int) $this->option('interval'));

        do {
            $killed = Reaper::sweep();
            foreach ($killed as $run) {
                // WARNING-level in Python, and the Grafana panel greps for
                // this phrasing — keep the wording recognisable.
                $this->warn(sprintf(
                    'Reaper killed run #%d shop=%s phase=%s close_reason=%s',
                    $run['run_id'],
                    $run['shop'],
                    $run['phase'],
                    $run['close_reason'],
                ));
            }
            if ($killed !== []) {
                $this->info(sprintf('Reaper iteration: %d run(s) killed', count($killed)));
            }
            if ($this->option('watch')) {
                sleep($interval);
            }
        } while ($this->option('watch'));

        return self::SUCCESS;
    }
}
