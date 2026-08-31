<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\ReadModel\ContinueReservation;
use App\DTO\ReadModel\RetryReservation;
use App\DTO\ReadModel\RunStateSnapshot;
use App\DTO\Request\RunMutationInput;
use App\Exceptions\ActionFailed;
use App\Models\ScrapeRun;
use App\Models\Shop;
use App\Runs\RunEvent;
use Illuminate\Database\ConnectionInterface;
use Illuminate\Database\DatabaseManager;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Carbon;

final readonly class RunSpawnRepository
{
    public function __construct(
        private DatabaseManager $database,
        private RunFailsafeRepository $events,
        private RunReconcilerRepository $reconciler,
    ) {}

    public function findWithShop(int $runId): ?ScrapeRun
    {
        return ScrapeRun::with('shop')->find($runId);
    }

    public function find(int $runId): ?ScrapeRun
    {
        return ScrapeRun::find($runId);
    }

    public function shopByName(string $name): ?Shop
    {
        return Shop::where('name', $name)->first();
    }

    public function shopName(int $shopId): ?string
    {
        $name = Shop::whereKey($shopId)->value('name');

        return is_string($name) ? $name : null;
    }

    public function activeRun(int $shopId, string $phase): ?ScrapeRun
    {
        $id = $this->connection()->table('scrape_runs')
            ->where('shop_id', $shopId)
            ->where('phase', $phase)
            ->whereIn('status', ['running', 'stopping', 'paused'])
            ->orderBy('id')
            ->value('id');

        $runId = DatabaseRow::from(['id' => $id])->nullableInt('id');

        return $runId === null ? null : ScrapeRun::find($runId);
    }

    public function pendingCount(int $runId): int
    {
        return $this->connection()->table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'pending')
            ->count();
    }

    public function reserveRerun(ScrapeRun $run): ?int
    {
        return $this->connection()->transaction(function () use ($run): ?int {
            $runId = $run->id;
            $hasPending = $run->status === 'failed'
                && $run->phase === 'scan'
                && $this->pendingCount($runId) > 0;

            if ($hasPending) {
                ScrapeRun::whereKey($runId)->update(['resumable_after_failure' => true]);
            }
            $this->events->recordEvent(
                $runId,
                RunEvent::RERUN,
                ['previous_status' => $run->status],
                RunEvent::ACTOR_OPERATOR,
            );

            return $hasPending ? $runId : null;
        });
    }

    public function reserveContinue(int $runId): ContinueReservation
    {
        return $this->connection()->transaction(function () use ($runId): ContinueReservation {
            $locked = $this->connection()->table('scrape_runs')->where('id', $runId)->lockForUpdate()->first();
            $run = $locked === null ? null : ScrapeRun::find($runId);
            if ($run === null) {
                throw ActionFailed::notFound(['detail' => 'Run not found']);
            }
            if ($run->status !== 'failed') {
                throw ActionFailed::badRequest([
                    'detail' => "Only failed runs can be continued; status='{$run->status}'",
                ]);
            }
            $pending = $this->pendingCount($runId);
            if ($pending === 0) {
                throw ActionFailed::badRequest([
                    'detail' => 'Nothing left to continue: no pending URLs on this run.',
                ]);
            }

            $previous = $this->snapshot($run);
            ScrapeRun::whereKey($runId)->update($this->runningValues());
            $this->reconciler->resetRetryableFailures($runId);
            $this->events->recordEvent(
                $runId,
                RunEvent::CONTINUED,
                ['pending_count' => $pending],
                RunEvent::ACTOR_OPERATOR,
            );

            return new ContinueReservation($run->phase, $previous);
        });
    }

    public function reserveRetry(RunMutationInput $input, int $runId): RetryReservation
    {
        return $this->connection()->transaction(function () use ($input, $runId): RetryReservation {
            $locked = $this->connection()->table('scrape_runs')->where('id', $runId)->lockForUpdate()->first();
            $run = $locked === null ? null : ScrapeRun::find($runId);
            if ($run === null) {
                throw ActionFailed::notFound(['detail' => 'Run not found']);
            }
            if ($run->phase !== 'scan') {
                throw ActionFailed::badRequest([
                    'detail' => "Retry is only supported for scan runs; phase='{$run->phase}'",
                ]);
            }

            $ids = $this->retryCandidates($input, $runId);
            if ($ids === []) {
                throw ActionFailed::badRequest(['detail' => 'No matching failed URLs to retry.']);
            }

            $this->connection()->table('scrape_url_items')->whereIn('id', $ids)->update([
                'status' => 'pending',
                'claimed_at' => null,
                'done_at' => null,
                'http_status' => null,
                'response_bytes' => null,
                'attempts' => 0,
            ]);
            $payload = $this->retryPayload($input);
            $payload['rows_reset'] = count($ids);
            $this->events->recordEvent(
                $runId,
                RunEvent::RETRY_FAILURES,
                $payload,
                RunEvent::ACTOR_OPERATOR,
            );

            $terminal = in_array($run->status, ['failed', 'completed'], true);
            $previous = $terminal ? $this->snapshot($run) : null;
            if ($terminal) {
                ScrapeRun::whereKey($runId)->update($this->runningValues());
            }

            return new RetryReservation(
                count($ids),
                $terminal,
                $run->status,
                $previous,
            );
        });
    }

    public function restore(int $runId, RunStateSnapshot $snapshot): void
    {
        ScrapeRun::whereKey($runId)->update($snapshot->toDatabaseValues());
    }

    public function hasRetryCandidates(RunMutationInput $input, int $runId): bool
    {
        return $this->retryQuery($input, $runId)->exists();
    }

    /** @return list<int> */
    private function retryCandidates(RunMutationInput $input, int $runId): array
    {
        $values = $this->retryQuery($input, $runId)
            ->pluck('sui.id')
            ->all();

        $ids = [];
        foreach ($values as $value) {
            $ids[] = DatabaseRow::from(['id' => $value])->int('id');
        }

        return $ids;
    }

    private function retryQuery(RunMutationInput $input, int $runId): Builder
    {
        $filtered = $input->errorReasonIsNull || $input->errorReason !== ''
            || $input->httpStatusIsNull || $input->httpStatus !== null;
        $query = $this->connection()->table('scrape_url_items as sui')
            ->where('sui.run_id', $runId)
            ->where('sui.status', 'failed');

        if (! $filtered) {
            return $query;
        }

        $latest = $this->connection()->table('scrape_failures')
            ->selectRaw(
                'scrape_url_item_id, error_reason, http_status,'
                .' row_number() over (partition by scrape_url_item_id'
                .' order by occurred_at desc, id desc) as rn',
            )
            ->where('run_id', $runId);
        $query->joinSub($latest, 'lf', 'lf.scrape_url_item_id', '=', 'sui.id')
            ->where('lf.rn', 1);

        if ($input->errorReasonIsNull) {
            $query->whereNull('lf.error_reason');
        } elseif ($input->errorReason !== '') {
            $query->where('lf.error_reason', $input->errorReason);
        }
        if ($input->httpStatusIsNull) {
            $query->whereNull('lf.http_status');
        } elseif ($input->httpStatus !== null) {
            $query->where('lf.http_status', $input->httpStatus);
        }

        return $query;
    }

    /** @return array<string, int|string|null> */
    private function retryPayload(RunMutationInput $input): array
    {
        $payload = [];
        if ($input->errorReasonIsNull) {
            $payload['error_reason_filter'] = null;
        } elseif ($input->errorReason !== '') {
            $payload['error_reason_filter'] = $input->errorReason;
        }
        if ($input->httpStatusIsNull) {
            $payload['http_status_filter'] = null;
        } elseif ($input->httpStatus !== null) {
            $payload['http_status_filter'] = $input->httpStatus;
        }

        return $payload;
    }

    private function snapshot(ScrapeRun $run): RunStateSnapshot
    {
        return new RunStateSnapshot(
            $run->status,
            $run->finished_at?->toISOString(),
            $run->close_reason,
            $run->last_heartbeat?->toISOString(),
            $run->pid,
        );
    }

    /** @return array<string, mixed> */
    private function runningValues(): array
    {
        return [
            'status' => 'running',
            'finished_at' => null,
            'close_reason' => null,
            'last_heartbeat' => Carbon::now('UTC'),
            'pid' => null,
        ];
    }

    private function connection(): ConnectionInterface
    {
        return $this->database->connection();
    }
}
