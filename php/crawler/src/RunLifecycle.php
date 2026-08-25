<?php

declare(strict_types=1);

namespace BookScraper\Crawler;

use BookScraper\Models\CronJob;
use BookScraper\Models\ScrapeRun;
use BookScraper\Runs\RunReconciler;
use BookScraper\Runs\ScanLock;
use RuntimeException;
use Illuminate\Support\Carbon;
use Throwable;

/**
 * Owns the scrape_runs row for one phase.
 *
 * The heartbeat is not cosmetic: the Python reaper flips a run to `failed`
 * when last_heartbeat goes stale, so a long PHP run that never touches it
 * gets reaped out from under itself.
 */
final class RunLifecycle
{
    private ?ScrapeRun $run = null;

    private bool $holdsLock = false;

    public function __construct(
        private readonly int $shopId,
        private readonly string $phase,
    ) {}

    /**
     * Open a run, refusing if another process already owns this shop+phase.
     *
     * The advisory lock is session-scoped and released in finish()/fail():
     * a transaction-scoped lock would drop the moment the run row commits,
     * leaving the rest of the crawl unprotected.
     */
    public function start(?int $urlsTotal = null): ScrapeRun
    {
        if (!ScanLock::tryAcquireForSession($this->shopId, $this->phase)) {
            throw new RuntimeException(sprintf(
                'another process is already running %s for this shop — refusing to '
                . 'start a second one (two crawls would fetch the same URLs)',
                $this->phase
            ));
        }
        $this->holdsLock = true;

        $run = ScrapeRun::start($this->shopId, $this->phase);
        if ($urlsTotal !== null) {
            $run->urls_total = $urlsTotal;
            $run->save();
        }
        $this->run = $run;

        return $run;
    }

    public function id(): ?int
    {
        return $this->run?->id;
    }

    public function run(): ?ScrapeRun
    {
        return $this->run;
    }

    /**
     * Take over an existing run row instead of opening a new one.
     *
     * A restart must stay on the SAME logical run: the depth cap and the
     * zero-progress breaker both count events on that row, so a fresh row
     * per attempt would hide the chain from them entirely.
     */
    public static function adopt(int $runId): self
    {
        $run = ScrapeRun::findOrFail($runId);
        $lifecycle = new self($run->shop_id, $run->phase);
        $lifecycle->run = $run;

        if (!ScanLock::tryAcquireForSession($run->shop_id, $run->phase)) {
            throw new RuntimeException(
                'another process already owns this shop+phase — refusing to adopt'
            );
        }
        $lifecycle->holdsLock = true;

        // Back to running, and no longer flagged for adoption — this process
        // owns the queue now.
        ScrapeRun::whereKey($runId)->update([
            'status' => 'running',
            'finished_at' => null,
            'resumable_after_failure' => false,
            'last_heartbeat' => Carbon::now('UTC'),
            'pid' => getmypid() ?: null,
        ]);

        // Inherit the queue. Items the dead process left mid-flight are
        // unowned, and failures with transient reasons deserve another go —
        // without both, a stalled run resumes with nothing to do and looks
        // like it completed.
        $released = RunReconciler::releaseStuckProcessing($runId);
        $retried = RunReconciler::resetRetryableFailures($runId);
        if ($released > 0 || $retried > 0) {
            printf(
                "  inherited queue: %d released from processing, %d retryable failure(s) reset\n",
                $released,
                $retried
            );
        }

        return $lifecycle;
    }

    /** Counters are written straight to the row, bypassing the model. */
    public function progress(int $processed, int $added, int $updated, int $errors): void
    {
        if ($this->run === null) {
            return;
        }

        ScrapeRun::whereKey($this->run->id)->update([
            'urls_processed' => $processed,
            'items_added' => $added,
            'items_updated' => $updated,
            'error_count' => $errors,
            'last_heartbeat' => Carbon::now('UTC'),
        ]);
    }

    public function finish(string $status = 'completed', ?string $closeReason = null): void
    {
        $this->run?->finish($status, $closeReason);
        $this->markCronJobRan();
        $this->releaseLock();
    }

    /**
     * Stamp last_run_at on every cron job for this shop+phase.
     *
     * Best-effort and unconditional on status, matching the Python services:
     * a failed run still ran, and the schedule page shows "last attempted",
     * not "last succeeded". Duplicate (shop, phase, strategy) rows are all
     * updated — the schema allows a morning and an evening job.
     */
    private function markCronJobRan(): void
    {
        [$phase, $strategy] = str_starts_with($this->phase, 'discover_')
            ? ['discover', substr($this->phase, strlen('discover_'))]
            : [$this->phase, null];
        // Only the data-producing phases stamp it — Python's validate and
        // match services don't, so neither does this.
        if (!in_array($phase, ['scan', 'discover'], true)) {
            return;
        }

        try {
            $query = CronJob::where('shop_id', $this->shopId)->where('phase', $phase);
            $strategy === null
                ? $query->whereNull('strategy')
                : $query->where('strategy', $strategy);
            $query->update(['last_run_at' => Carbon::now('UTC')]);
        } catch (Throwable $e) {
            fwrite(STDERR, "  could not stamp cron last_run_at: {$e->getMessage()}\n");
        }
    }

    private function releaseLock(): void
    {
        if ($this->holdsLock) {
            ScanLock::release($this->shopId, $this->phase);
            $this->holdsLock = false;
        }
    }

    /** Records the failure with its reason so the run isn't left running. */
    public function fail(Throwable $e): void
    {
        $this->finish('failed', substr($e->getMessage(), 0, 500));
    }
}
