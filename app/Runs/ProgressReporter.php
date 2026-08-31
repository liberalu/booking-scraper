<?php

declare(strict_types=1);

namespace App\Runs;

use App\Repositories\ProgressReporterRepository;
use Closure;

final class ProgressReporter
{
    private const EVERY = 10;

    private ?int $runId = null;

    /** @var (Closure(array<string, int>): int)|null */
    private ?Closure $processedFrom = null;

    private int $ticks = 0;

    public function __construct(
        private readonly ProgressReporterRepository $repository = new ProgressReporterRepository,
    ) {}

    /** @param callable(array<string, int>): int $processedFrom */
    public function bind(?int $runId, callable $processedFrom): void
    {
        $this->runId = $runId;
        $this->processedFrom = Closure::fromCallable($processedFrom);
        $this->ticks = 0;
    }

    public function reset(): void
    {
        $this->runId = null;
        $this->processedFrom = null;
        $this->ticks = 0;
    }

    /** @param array<string, int> $tally */
    public function tick(array $tally): void
    {
        $this->ticks++;
        if ($this->ticks % self::EVERY === 0) {
            $this->flush($tally);
        }
    }

    /** @param array<string, int> $tally */
    public function flush(array $tally): void
    {
        if ($this->runId === null || $this->processedFrom === null) {
            return;
        }

        $this->repository->write(
            $this->runId,
            ($this->processedFrom)($tally),
            $tally,
        );
    }
}
