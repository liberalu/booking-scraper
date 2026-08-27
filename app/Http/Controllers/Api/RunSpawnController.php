<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\CrawlSpawner;
use App\Support\Config;
use App\Models\ScrapeRun;
use App\Models\Shop;
use App\Runs\RunEvent;
use App\Runs\RunFailsafe;
use App\Runs\RunReconciler;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Throwable;

/**
 * The four endpoints that start a crawl.
 *
 * Each one validates everything it can BEFORE spawning — an unknown shop, a
 * broken config, a run already active for the same shop+phase — because a
 * half-started run with rows already mutated is far worse than a 4xx.
 */
final class RunSpawnController
{
    private const PHASES = ['scan', 'discover', 'match', 'validate'];

    /** @return array<string, mixed>|JsonResponse */
    public function store(Request $request): mixed
    {
        $phase = (string) $request->input('phase', 'scan');
        if (!in_array($phase, self::PHASES, true)) {
            return response()->json(['detail' => "Unknown phase: {$phase}"], 400);
        }
        $shopName = (string) $request->input('shop', '');
        $strategy = (string) $request->input('strategy', '');
        $mode = (string) $request->input('mode', 'delta');
        $urls = (string) $request->input('urls', '');
        $cronJobId = $request->input('cron_job_id');
        $cronJobId = $cronJobId === null ? null : (int) $cronJobId;

        $runPhase = ($phase === 'discover' && $strategy !== '')
            ? "discover_{$strategy}"
            : $phase;

        $failure = $this->preflight($shopName, $runPhase);
        if ($failure !== null) {
            return $failure;
        }

        try {
            CrawlSpawner::spawn($phase, $shopName, $strategy, $mode, $urls, $cronJobId);
        } catch (Throwable $e) {
            return response()->json(['detail' => $e->getMessage()], 503);
        }

        return [
            'status' => 'started',
            'shop' => $shopName,
            'phase' => $phase,
            'strategy' => $strategy,
            'mode' => $mode,
        ];
    }

    /**
     * Re-fire a terminal run.
     *
     * The failed row is flagged resumable so the new process adopts its
     * queue on the same row rather than opening a second one.
     *
     * @return array<string, mixed>|JsonResponse
     */
    public function rerun(int $runId): mixed
    {
        $run = ScrapeRun::with('shop')->find($runId);
        if ($run === null) {
            return response()->json(['detail' => 'Run not found'], 404);
        }
        if (!in_array($run->status, ['failed', 'completed'], true)) {
            return response()->json([
                'detail' => "Only terminal runs can be re-run; status='{$run->status}'",
            ], 400);
        }

        $shopName = (string) $run->shop->name;
        $failure = $this->preflight($shopName, (string) $run->phase);
        if ($failure !== null) {
            return $failure;
        }

        DB::transaction(function () use ($run, $runId): void {
            // completed runs have no pending items, so the flag is harmless.
            if ($run->status === 'failed') {
                ScrapeRun::whereKey($runId)->update(['resumable_after_failure' => true]);
            }
            RunFailsafe::recordEvent(
                $runId,
                RunEvent::RERUN,
                ['previous_status' => $run->status],
                RunEvent::ACTOR_OPERATOR,
            );
        });

        [$phase, $strategy] = self::splitPhase((string) $run->phase);
        try {
            CrawlSpawner::spawn($phase, $shopName, $strategy);
        } catch (Throwable $e) {
            return response()->json(['detail' => $e->getMessage()], 503);
        }

        return ['status' => 'started', 'rerun_of' => $runId, 'shop' => $shopName];
    }

    /**
     * Resume a failed run on the same row.
     *
     * Row-locked against a concurrent Continue, and rolled back to the prior
     * terminal state if the spawn itself fails — otherwise a failed spawn
     * would leave a `running` run with no process behind it.
     *
     * @return array<string, mixed>|JsonResponse
     */
    public function continueRun(int $runId): mixed
    {
        $locked = DB::table('scrape_runs')->where('id', $runId)->lockForUpdate()->first();
        if ($locked === null) {
            return response()->json(['detail' => 'Run not found'], 404);
        }
        if ($locked->status !== 'failed') {
            return response()->json([
                'detail' => "Only failed runs can be continued; status='{$locked->status}'",
            ], 400);
        }

        $pending = DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'pending')
            ->count();
        if ($pending === 0) {
            return response()->json([
                'detail' => 'Nothing left to continue: no pending URLs on this run.',
            ], 400);
        }

        $shopName = Shop::whereKey($locked->shop_id)->value('name');
        if ($shopName === null) {
            return response()->json(['detail' => 'Shop not found'], 404);
        }
        $failure = $this->preflight((string) $shopName, (string) $locked->phase);
        if ($failure !== null) {
            return $failure;
        }

        $previous = [
            'status' => 'failed',
            'finished_at' => $locked->finished_at,
            'close_reason' => $locked->close_reason,
            'last_heartbeat' => $locked->last_heartbeat,
            'pid' => $locked->pid,
        ];

        DB::transaction(function () use ($runId, $pending): void {
            ScrapeRun::whereKey($runId)->update([
                'status' => 'running',
                'finished_at' => null,
                'close_reason' => null,
                'last_heartbeat' => Carbon::now('UTC'),
                'pid' => null,
            ]);
            // Same reset auto-resume performs, so Continue and a stall
            // restart leave the queue in the same shape.
            RunReconciler::resetRetryableFailures($runId);
            RunFailsafe::recordEvent(
                $runId,
                RunEvent::CONTINUED,
                ['pending_count' => $pending],
                RunEvent::ACTOR_OPERATOR,
            );
        });

        [$phase, $strategy] = self::splitPhase((string) $locked->phase);
        try {
            CrawlSpawner::spawn($phase, (string) $shopName, $strategy);
        } catch (Throwable $e) {
            ScrapeRun::whereKey($runId)->update($previous);

            return response()->json(['detail' => $e->getMessage()], 503);
        }

        return ['status' => 'continued', 'run_id' => $runId, 'shop' => $shopName];
    }

    /**
     * Reset failed URLs to pending so they get scraped again.
     *
     * A live run's resident spider picks the rows up on its next claim
     * cycle; a terminal run needs a fresh process, so this also revives it.
     *
     * @return array<string, mixed>|JsonResponse
     */
    public function retry(Request $request, int $runId): mixed
    {
        $locked = DB::table('scrape_runs')->where('id', $runId)->lockForUpdate()->first();
        if ($locked === null) {
            return response()->json(['detail' => 'Run not found'], 404);
        }
        if ($locked->phase !== 'scan') {
            return response()->json([
                'detail' => "Retry is only supported for scan runs; phase='{$locked->phase}'",
            ], 400);
        }

        $errorReason = (string) $request->query('error_reason', '');
        $reasonIsNull = self::flag($request, 'error_reason_is_null');
        $httpStatusRaw = $request->query('http_status');
        $httpStatus = ($httpStatusRaw === null || $httpStatusRaw === '')
            ? null
            : (int) $httpStatusRaw;
        $statusIsNull = self::flag($request, 'http_status_is_null');

        $candidateIds = $this->retryCandidates(
            $runId,
            $errorReason,
            $reasonIsNull,
            $httpStatus,
            $statusIsNull
        );
        $matches = count($candidateIds);
        if ($matches === 0) {
            return response()->json(['detail' => 'No matching failed URLs to retry.'], 400);
        }

        $isTerminal = in_array($locked->status, ['failed', 'completed'], true);
        $shopName = null;
        if ($isTerminal) {
            // Validate before touching rows: pending rows on a run that
            // cannot be revived are worse than a 4xx.
            $shopName = Shop::whereKey($locked->shop_id)->value('name');
            if ($shopName === null) {
                return response()->json(['detail' => 'Shop not found'], 404);
            }
            $failure = $this->preflight((string) $shopName, (string) $locked->phase);
            if ($failure !== null) {
                return $failure;
            }
        }

        $payload = ['rows_reset' => $matches];
        if ($reasonIsNull) {
            $payload['error_reason_filter'] = null;
        } elseif ($errorReason !== '') {
            $payload['error_reason_filter'] = $errorReason;
        }
        if ($statusIsNull) {
            $payload['http_status_filter'] = null;
        } elseif ($httpStatus !== null) {
            $payload['http_status_filter'] = $httpStatus;
        }

        DB::transaction(function () use ($candidateIds, $runId, $payload): void {
            // Operator retry is the explicit override: zeroing `attempts`
            // gives capped items a fresh window. The end-of-run sweep does
            // not, so a persistently dead URL still retires on its own.
            DB::table('scrape_url_items')->whereIn('id', $candidateIds)->update([
                'status' => 'pending',
                'claimed_at' => null,
                'done_at' => null,
                'http_status' => null,
                'response_bytes' => null,
                'attempts' => 0,
            ]);
            RunFailsafe::recordEvent(
                $runId,
                RunEvent::RETRY_FAILURES,
                $payload,
                RunEvent::ACTOR_OPERATOR,
            );
        });

        if (!$isTerminal) {
            return [
                'retried' => $matches,
                'run_id' => $runId,
                'run_status' => $locked->status,
                'spawned' => false,
            ];
        }

        $previous = [
            'status' => $locked->status,
            'finished_at' => $locked->finished_at,
            'close_reason' => $locked->close_reason,
            'last_heartbeat' => $locked->last_heartbeat,
            'pid' => $locked->pid,
        ];
        ScrapeRun::whereKey($runId)->update([
            'status' => 'running',
            'finished_at' => null,
            'close_reason' => null,
            'last_heartbeat' => Carbon::now('UTC'),
            'pid' => null,
        ]);

        try {
            CrawlSpawner::spawn('scan', (string) $shopName);
        } catch (Throwable $e) {
            // The row resets stay: the operator can retry the spawn, or
            // call /continue, without losing them.
            ScrapeRun::whereKey($runId)->update($previous);

            return response()->json(['detail' => $e->getMessage()], 503);
        }

        return [
            'retried' => $matches,
            'run_id' => $runId,
            'run_status' => 'running',
            'spawned' => true,
        ];
    }

    /**
     * Items whose LATEST failure matches the requested bucket and whose queue
     * row is still `failed` — the same grouping the failure card showed, so
     * retry acts on exactly the rows the operator was looking at.
     *
     * @return list<int>
     */
    private function retryCandidates(
        int $runId,
        string $errorReason,
        bool $reasonIsNull,
        ?int $httpStatus,
        bool $statusIsNull,
    ): array {
        $needsFailureFilter = $reasonIsNull || $errorReason !== ''
            || $statusIsNull || $httpStatus !== null;

        $query = DB::table('scrape_url_items as sui')
            ->where('sui.run_id', $runId)
            ->where('sui.status', 'failed');

        if ($needsFailureFilter) {
            $latest = DB::table('scrape_failures')
                ->selectRaw(
                    'scrape_url_item_id, error_reason, http_status,'
                    . ' row_number() over (partition by scrape_url_item_id'
                    . ' order by occurred_at desc, id desc) as rn'
                )
                ->where('run_id', $runId);

            $query->joinSub($latest, 'lf', 'lf.scrape_url_item_id', '=', 'sui.id')
                ->where('lf.rn', 1);
            if ($reasonIsNull) {
                $query->whereNull('lf.error_reason');
            } elseif ($errorReason !== '') {
                $query->where('lf.error_reason', $errorReason);
            }
            if ($statusIsNull) {
                $query->whereNull('lf.http_status');
            } elseif ($httpStatus !== null) {
                $query->where('lf.http_status', $httpStatus);
            }
        }

        return $query->pluck('sui.id')->map(static fn ($id): int => (int) $id)->all();
    }

    /**
     * Shop exists, its config parses, and nothing is already running for the
     * same shop+phase. Returns the response to send, or null to proceed.
     */
    private function preflight(string $shopName, string $runPhase): ?JsonResponse
    {
        $shop = Shop::where('name', $shopName)->first();
        if ($shop === null) {
            return response()->json(['detail' => "Unknown shop: {$shopName}"], 404);
        }
        try {
            Config::forShop($shopName);
        } catch (Throwable $e) {
            return response()->json(
                ['detail' => "Shop config failed to load: {$e->getMessage()}"],
                400
            );
        }
        // `stopping` counts as active: a second run while the first tears
        // down would double the load on the shop.
        // orderBy('id'): with two active runs an unordered first() names an
        // arbitrary one, and which one moves when a status UPDATE rewrites the
        // row. The oldest active run is the one actually blocking, and it is
        // the same answer every time. Python orders identically.
        $existing = ScrapeRun::where('shop_id', $shop->id)
            ->where('phase', $runPhase)
            ->whereIn('status', ['running', 'stopping', 'paused'])
            ->orderBy('id')
            ->first();
        if ($existing !== null) {
            return response()->json([
                'detail' => "A {$runPhase} run for {$shop->name} is already "
                    . "{$existing->status} (run #{$existing->id}).",
            ], 409);
        }

        return null;
    }

    /** 'discover_sitemap' -> ['discover', 'sitemap']; 'scan' -> ['scan', '']. */
    private static function splitPhase(string $runPhase): array
    {
        if (str_starts_with($runPhase, 'discover_')) {
            return ['discover', substr($runPhase, strlen('discover_'))];
        }

        return [$runPhase, ''];
    }

    /** FastAPI accepts true/1/yes/on for a bool query param. */
    private static function flag(Request $request, string $key): bool
    {
        $raw = $request->query($key);
        if ($raw === null) {
            return false;
        }

        return in_array(strtolower((string) $raw), ['true', '1', 'yes', 'on'], true);
    }
}
