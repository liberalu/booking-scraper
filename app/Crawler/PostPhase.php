<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Contracts\RunLauncher;
use App\Models\CronJob;
use App\Repositories\PostPhaseRepository;
use App\Runs\RunEvent;
use App\Runs\RunFailsafe;
use App\Services\MatchService;
use App\Support\CronSchedule;
use Throwable;

final readonly class PostPhase
{
    private const string SPAWN_CONTEXT = 'post-phase-auto';

    public function __construct(
        private PostPhaseRepository $repository,
        private MatchService $matcher,
        private RunFailsafe $failsafe,
        private RunLauncher $launcher,
    ) {}

    public function after(
        string $phase,
        string $shopName,
        int $runId,
        ?int $cronJobId,
    ): void {
        $chainJob = $cronJobId === null ? null : $this->chainTarget($cronJobId);

        if ($chainJob instanceof CronJob) {
            $this->spawnCronChain($chainJob);
            if (in_array($chainJob->phase, ['match', 'validate'], true)) {

                return;
            }
        }

        if (! $this->autoTriggerEnabled()) {
            fwrite(STDOUT, "post-phase: disabled via env, skipping\n");

            return;
        }

        try {
            $linked = $this->matcher->isbnMatch($shopName);
            printf("post-phase: ISBN-match linked %d shop_book(s)\n", $linked);
        } catch (Throwable $e) {
            fwrite(STDERR, "post-phase: ISBN-match failed: {$e->getMessage()}\n");
        }

        $this->spawnValidate($shopName);
    }

    public function chainSkipped(int $runId, ?int $cronJobId, string $reason): void
    {
        if ($cronJobId === null) {
            return;
        }
        try {
            $this->failsafe->recordEvent($runId, RunEvent::CHAIN_SKIPPED, [
                'parent_reason' => $reason,
                'cron_job_id' => $cronJobId,
            ]);
        } catch (Throwable $e) {
            fwrite(STDERR, "post-phase: could not record chain_skipped: {$e->getMessage()}\n");
        }
    }

    private function chainTarget(int $cronJobId): ?CronJob
    {
        try {
            return $this->repository->chainTarget($cronJobId);
        } catch (Throwable $e) {
            fwrite(STDERR, "post-phase: chain lookup failed: {$e->getMessage()}\n");

            return null;
        }
    }

    private function spawnCronChain(CronJob $job): void
    {
        $shop = $job->shop->name;
        $phase = $job->phase;
        $translated = CronSchedule::translateArgs($job->args ?? '');
        if ($translated['unknown'] !== []) {
            fwrite(STDERR, 'post-phase: unsupported chain arguments: '.implode(', ', $translated['unknown'])."\n");

            return;
        }

        try {
            $result = $this->launcher->spawn(
                phase: $phase,
                shop: $shop,
                strategy: $job->strategy ?? '',
                mode: $translated['mode'] ?? 'delta',
                cronJobId: $job->id,
                role: 'cron-chain',
            );
            printf("post-phase: spawned chain job %d (%s) log=%s\n", $job->id, $phase, $result['log']);
        } catch (Throwable $exception) {
            fwrite(STDERR, "post-phase: chain spawn failed: {$exception->getMessage()}\n");
        }
    }

    private function spawnValidate(string $shopName): void
    {
        try {
            $result = $this->launcher->spawn('validate', $shopName, role: self::SPAWN_CONTEXT);
            printf("post-phase: spawned validate for %s log=%s\n", $shopName, $result['log']);
        } catch (Throwable $exception) {
            fwrite(STDERR, "post-phase: validate spawn failed: {$exception->getMessage()}\n");
        }
    }

    private function autoTriggerEnabled(): bool
    {

        $raw = getenv('POST_PHASE_AUTO_TRIGGER');
        if (! is_string($raw) || $raw === '') {
            $raw = getenv('POST_SCAN_AUTO_TRIGGER');
        }
        if (! is_string($raw) || $raw === '') {
            return true;
        }

        return in_array(strtolower($raw), ['1', 'true', 'yes', 'on'], true);
    }
}
