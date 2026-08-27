<?php

declare(strict_types=1);

namespace App\Crawler\Scheduling;

use RoachPHP\Http\Request;
use RoachPHP\Scheduling\RequestSchedulerInterface;
use RoachPHP\Scheduling\Timing\ClockInterface;

/**
 * Drop-in replacement for roach's ArrayRequestScheduler that paces in
 * fractional seconds.
 *
 * RequestSchedulerInterface::setDelay() is typed `int`, so the float
 * delay arrives through setDelaySeconds() instead — Config::downloadDelay()
 * is the source. setDelay() is still honoured (roach's Engine calls it
 * with the spider's int) but only when no float has been set, so the
 * interface stays satisfied without letting an int silently overwrite the
 * real per-shop value.
 *
 * ponytail: mirrors ArrayRequestScheduler rather than subclassing it —
 * that class is final. Re-check on roach upgrades.
 */
final class SubSecondRequestScheduler implements RequestSchedulerInterface
{
    private float $delay = 0.0;

    private bool $delayExplicitlySet = false;

    /** @var list<Request> */
    private array $requests = [];

    private \DateTimeImmutable $nextBatchReadyAt;

    public function __construct(private readonly ClockInterface $clock)
    {
        $this->nextBatchReadyAt = $this->clock->now();
    }

    /** The per-shop `download_delay`, in fractional seconds. */
    public function setDelaySeconds(float $seconds): self
    {
        $this->delay = max(0.0, $seconds);
        $this->delayExplicitlySet = true;

        return $this;
    }

    public function schedule(Request $request): void
    {
        $this->requests[] = $request;
    }

    public function empty(): bool
    {
        return $this->requests === [];
    }

    /** @return array<array-key, Request> */
    public function nextRequests(int $batchSize): array
    {
        $this->clock->sleepUntil($this->nextBatchReadyAt);
        $this->nextBatchReadyAt = $this->addDelay($this->clock->now());

        return $this->take($batchSize);
    }

    /** @return array<array-key, Request> */
    public function forceNextRequests(int $batchSize): array
    {
        return $this->take($batchSize);
    }

    public function setDelay(int $delay): RequestSchedulerInterface
    {
        // Don't let the spider's int clobber a float already set from the
        // shop config — that is exactly the truncation this class exists
        // to avoid.
        if (!$this->delayExplicitlySet) {
            $this->delay = (float) $delay;
        }

        return $this;
    }

    public function setNamespace(string $namespace): RequestSchedulerInterface
    {
        return $this;
    }

    public function delaySeconds(): float
    {
        return $this->delay;
    }

    private function addDelay(\DateTimeImmutable $from): \DateTimeImmutable
    {
        if ($this->delay <= 0.0) {
            return $from;
        }

        return $from->modify(sprintf('+%d microseconds', (int) round($this->delay * 1_000_000)))
            ?: $from;
    }

    /** @return array<array-key, Request> */
    private function take(int $batchSize): array
    {
        return \array_splice($this->requests, 0, $batchSize);
    }
}
