<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\CronJob;
use App\Models\ScrapeRun;
use App\Repositories\Contracts\RunLifecycleRepositoryInterface;
use App\Runs\RunEvent;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;

final readonly class RunLifecycleRepository implements RunLifecycleRepositoryInterface
{
    public function __construct(
        private RunFinisherRepository $finisher = new RunFinisherRepository,
        private RunFailsafeRepository $events = new RunFailsafeRepository,
    ) {}

    public function start(int $shopId, string $phase, ?int $urlsTotal): ScrapeRun
    {
        $pid = getmypid();

        return DB::transaction(function () use ($shopId, $phase, $urlsTotal, $pid): ScrapeRun {
            $run = ScrapeRun::create([
                'shop_id' => $shopId,
                'phase' => $phase,
                'status' => 'running',
                'started_at' => Date::now('UTC'),
                'last_heartbeat' => Date::now('UTC'),
                'pid' => $pid === false ? null : $pid,
                'urls_total' => $urlsTotal,
            ]);
            $this->events->recordEvent($run->id, RunEvent::STARTED, [
                'phase' => $phase,
                'urls_total' => $urlsTotal,
            ]);

            return $run;
        });
    }

    public function find(int $runId): ScrapeRun
    {
        return ScrapeRun::findOrFail($runId);
    }

    public function adopt(int $runId): void
    {
        $pid = getmypid();

        ScrapeRun::whereKey($runId)->update([
            'status' => 'running',
            'finished_at' => null,
            'close_reason' => null,
            'resumable_after_failure' => false,
            'last_heartbeat' => Date::now('UTC'),
            'pid' => $pid === false ? null : $pid,
        ]);
    }

    public function progress(
        int $runId,
        int $processed,
        int $added,
        int $updated,
        int $errors,
    ): void {
        ScrapeRun::whereKey($runId)->update([
            'urls_processed' => $processed,
            'items_added' => $added,
            'items_updated' => $updated,
            'error_count' => $errors,
            'last_heartbeat' => Date::now('UTC'),
        ]);
    }

    public function finish(int $runId, string $status, ?string $closeReason): void
    {
        $this->finisher->finish($runId, $status, $closeReason);
    }

    public function stampCronJob(int $shopId, string $phase, ?string $strategy): void
    {
        $query = CronJob::where('shop_id', $shopId)->where('phase', $phase);
        $query->where('strategy', $strategy);
        $query->update(['last_run_at' => Date::now('UTC')]);
    }
}
