<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Runs\Reaper;
use Illuminate\Console\Command;
use Illuminate\Support\Sleep;

final class ReapRuns extends Command
{
    protected $signature = 'runs:reap
        {--watch : keep sweeping instead of exiting after one pass}
        {--interval=30 : seconds between sweeps in --watch mode}';

    protected $description = 'Fail runs whose heartbeat has gone stale';

    public function __construct(private readonly Reaper $reaper)
    {
        parent::__construct();
    }

    public function handle(): int
    {
        $interval = max(5, (int) $this->option('interval'));

        do {
            $killed = $this->reaper->sweep();
            foreach ($killed as $run) {

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
                Sleep::sleep($interval);
            }
        } while ($this->option('watch'));

        return self::SUCCESS;
    }
}
