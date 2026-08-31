<?php

declare(strict_types=1);

namespace App\Crawler\Scheduling;

use RoachPHP\Http\Request;
use RoachPHP\Scheduling\RequestSchedulerInterface;
use RoachPHP\Scheduling\Timing\ClockInterface;

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

    public function nextRequests(int $batchSize): array
    {
        $this->clock->sleepUntil($this->nextBatchReadyAt);
        $this->nextBatchReadyAt = $this->addDelay($this->clock->now());

        return $this->take($batchSize);
    }

    public function forceNextRequests(int $batchSize): array
    {
        return $this->take($batchSize);
    }

    public function setDelay(int $delay): RequestSchedulerInterface
    {

        if (! $this->delayExplicitlySet) {
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

        return $from->modify(sprintf(
            '+%d microseconds',
            (int) round($this->delay * 1_000_000),
        ));
    }

    /** @return list<Request> */
    private function take(int $batchSize): array
    {
        return \array_splice($this->requests, 0, $batchSize);
    }
}
