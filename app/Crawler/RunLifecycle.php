<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Models\ScrapeRun;
use App\Repositories\Contracts\RunLifecycleRepositoryInterface;
use App\Repositories\RunLifecycleRepository;
use App\Runs\RunReconciler;
use App\Runs\ScanLock;
use RuntimeException;
use Throwable;

final class RunLifecycle
{
    private ?ScrapeRun $run = null;

    private bool $holdsLock = false;

    public function __construct(
        private readonly int $shopId,
        private readonly string $phase,
        private readonly RunLifecycleRepositoryInterface $runs = new RunLifecycleRepository,
        private readonly ScanLock $scanLock = new ScanLock,
    ) {}

    public function start(?int $urlsTotal = null): ScrapeRun
    {
        if (! $this->scanLock->tryAcquireForSession($this->shopId)) {
            throw new RuntimeException(sprintf(
                'another process is already running %s for this shop — refusing to '
                .'start a second one (two crawls would fetch the same URLs)',
                $this->phase
            ));
        }
        $this->holdsLock = true;

        $run = $this->runs->start($this->shopId, $this->phase, $urlsTotal);
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

    public static function adopt(int $runId): self
    {
        $repository = new RunLifecycleRepository;
        $run = $repository->find($runId);
        $scanLock = new ScanLock;
        $reconciler = new RunReconciler;
        $shopId = $run->shop_id;
        $phase = $run->phase;
        $lifecycle = new self($shopId, $phase, $repository, $scanLock);
        $lifecycle->run = $run;

        if (! $scanLock->tryAcquireForSession($shopId)) {
            throw new RuntimeException(
                'another process already owns this shop+phase — refusing to adopt'
            );
        }
        $lifecycle->holdsLock = true;

        $repository->adopt($runId);

        $released = $reconciler->releaseStuckProcessing($runId);
        $retried = $reconciler->resetRetryableFailures($runId);
        if ($released > 0 || $retried > 0) {
            printf(
                "  inherited queue: %d released from processing, %d retryable failure(s) reset\n",
                $released,
                $retried
            );
        }

        return $lifecycle;
    }

    public function progress(int $processed, int $added, int $updated, int $errors): void
    {
        if (! $this->run instanceof ScrapeRun) {
            return;
        }

        $this->runs->progress($this->run->id, $processed, $added, $updated, $errors);
    }

    public function finish(string $status = 'completed', ?string $closeReason = null): void
    {
        if ($this->run instanceof ScrapeRun) {
            $this->runs->finish($this->run->id, $status, $closeReason);
        }
        $this->markCronJobRan();
        $this->releaseLock();
    }

    private function markCronJobRan(): void
    {
        [$phase, $strategy] = str_starts_with($this->phase, 'discover_')
            ? ['discover', substr($this->phase, strlen('discover_'))]
            : [$this->phase, null];

        if (! in_array($phase, ['scan', 'discover'], true)) {
            return;
        }

        try {
            $this->runs->stampCronJob($this->shopId, $phase, $strategy);
        } catch (Throwable $e) {
            fwrite(STDERR, "  could not stamp cron last_run_at: {$e->getMessage()}\n");
        }
    }

    private function releaseLock(): void
    {
        if ($this->holdsLock) {
            $this->scanLock->release($this->shopId);
            $this->holdsLock = false;
        }
    }

    public function fail(Throwable $e): void
    {
        $this->finish('failed', substr($e->getMessage(), 0, 500));
    }
}
