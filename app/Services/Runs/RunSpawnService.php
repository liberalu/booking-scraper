<?php

declare(strict_types=1);

namespace App\Services\Runs;

use App\Contracts\RunLauncher;
use App\DTO\ReadModel\RunStateSnapshot;
use App\DTO\Request\RunMutationInput;
use App\Exceptions\ActionFailed;
use App\Models\ScrapeRun;
use App\Models\Shop;
use App\Repositories\RunSpawnRepository;
use App\Runs\RunLaunchRequest;
use App\Runs\RunPhase;
use App\Support\Config;
use Throwable;

final readonly class RunSpawnService
{
    public function __construct(
        private RunSpawnRepository $runs,
        private RunLauncher $launcher,
    ) {}

    /** @return array{status: string, shop: string, phase: string, strategy: string, mode: string} */
    public function store(RunMutationInput $input): array
    {
        $phase = RunPhase::tryFrom($input->phase);
        if ($phase === null) {
            throw ActionFailed::badRequest(['detail' => "Unknown phase: {$input->phase}"]);
        }
        if (! in_array($input->mode, ['delta', 'full', 'sample'], true)) {
            throw ActionFailed::badRequest(['detail' => "Unknown scan mode: {$input->mode}"]);
        }
        if ($input->strategy !== '' && $phase !== RunPhase::Discover) {
            throw ActionFailed::badRequest([
                'detail' => 'A discovery strategy only applies to discover runs',
            ]);
        }
        if ($input->urls !== '' && $input->mode !== 'delta') {
            throw ActionFailed::badRequest([
                'detail' => 'Explicit URLs cannot be combined with a scan mode',
            ]);
        }

        $runPhase = $phase === RunPhase::Discover && $input->strategy !== ''
            ? "discover_{$input->strategy}"
            : $input->phase;
        $this->preflight($input->shop, $runPhase);
        $this->spawnRequest(new RunLaunchRequest(
            phase: $phase,
            shop: $input->shop,
            strategy: $input->strategy,
            mode: $input->mode,
            urls: $input->urls,
            cronJobId: $input->cronJobId,
        ));

        return [
            'status' => 'started',
            'shop' => $input->shop,
            'phase' => $input->phase,
            'strategy' => $input->strategy,
            'mode' => $input->mode,
        ];
    }

    /** @return array{status: string, rerun_of: int, shop: string} */
    public function rerun(ScrapeRun $boundRun): array
    {
        $runId = $boundRun->id;
        $run = $this->runs->findWithShop($runId);
        if (! $run instanceof ScrapeRun) {
            throw ActionFailed::notFound(['detail' => 'Run not found']);
        }
        if (! in_array($run->status, ['failed', 'completed'], true)) {
            throw ActionFailed::badRequest([
                'detail' => "Only terminal runs can be re-run; status='{$run->status}'",
            ]);
        }

        $shop = $run->shop->name;
        $this->preflight($shop, $run->phase);
        $adoptRunId = $this->runs->reserveRerun($run);
        [$phase, $strategy] = $this->splitPhase($run->phase);
        $this->spawn($phase, $shop, $strategy, adoptRunId: $adoptRunId);

        return ['status' => 'started', 'rerun_of' => $runId, 'shop' => $shop];
    }

    /** @return array{status: string, run_id: int, shop: string} */
    public function continueRun(ScrapeRun $boundRun): array
    {
        $runId = $boundRun->id;
        $run = $this->runs->find($runId);
        if (! $run instanceof ScrapeRun) {
            throw ActionFailed::notFound(['detail' => 'Run not found']);
        }
        if ($run->status !== 'failed') {
            throw ActionFailed::badRequest([
                'detail' => "Only failed runs can be continued; status='{$run->status}'",
            ]);
        }
        if ($this->runs->pendingCount($runId) === 0) {
            throw ActionFailed::badRequest([
                'detail' => 'Nothing left to continue: no pending URLs on this run.',
            ]);
        }

        $shop = $this->runs->shopName($run->shop_id);
        if ($shop === null) {
            throw ActionFailed::notFound(['detail' => 'Shop not found']);
        }
        $this->preflight($shop, $run->phase);
        $reservation = $this->runs->reserveContinue($runId);
        [$phase, $strategy] = $this->splitPhase($reservation->phase);

        try {
            $this->spawn($phase, $shop, $strategy, adoptRunId: $runId);
        } catch (ActionFailed $e) {
            $this->runs->restore($runId, $reservation->previous);

            throw $e;
        }

        return ['status' => 'continued', 'run_id' => $runId, 'shop' => $shop];
    }

    /** @return array{retried: int, run_id: int, run_status: string, spawned: bool} */
    public function retry(RunMutationInput $input, ScrapeRun $boundRun): array
    {
        $runId = $boundRun->id;
        $run = $this->runs->find($runId);
        if (! $run instanceof ScrapeRun) {
            throw ActionFailed::notFound(['detail' => 'Run not found']);
        }
        if ($run->phase !== 'scan') {
            throw ActionFailed::badRequest([
                'detail' => "Retry is only supported for scan runs; phase='{$run->phase}'",
            ]);
        }
        if (! $this->runs->hasRetryCandidates($input, $runId)) {
            throw ActionFailed::badRequest(['detail' => 'No matching failed URLs to retry.']);
        }

        $terminal = in_array($run->status, ['failed', 'completed'], true);
        $shop = null;
        if ($terminal) {
            $shop = $this->runs->shopName($run->shop_id);
            if ($shop === null) {
                throw ActionFailed::notFound(['detail' => 'Shop not found']);
            }
            $this->preflight($shop, $run->phase);
        }

        $reservation = $this->runs->reserveRetry($input, $runId);
        if (! $reservation->terminal) {
            return [
                'retried' => $reservation->matches,
                'run_id' => $runId,
                'run_status' => $reservation->status,
                'spawned' => false,
            ];
        }

        if ($shop === null) {
            throw ActionFailed::notFound(['detail' => 'Shop not found']);
        }

        try {
            $this->spawn('scan', $shop, adoptRunId: $runId);
        } catch (ActionFailed $e) {
            if ($reservation->previous instanceof RunStateSnapshot) {
                $this->runs->restore($runId, $reservation->previous);
            }

            throw $e;
        }

        return [
            'retried' => $reservation->matches,
            'run_id' => $runId,
            'run_status' => 'running',
            'spawned' => true,
        ];
    }

    private function preflight(string $shopName, string $phase): void
    {
        $shop = $this->runs->shopByName($shopName);
        if (! $shop instanceof Shop) {
            throw ActionFailed::notFound(['detail' => "Unknown shop: {$shopName}"]);
        }
        try {
            $config = Config::forShop($shopName);
        } catch (Throwable) {
            throw ActionFailed::badRequest([
                'detail' => 'Shop configuration is invalid',
            ]);
        }

        [$basePhase, $strategy] = $this->splitPhase($phase);
        if ($basePhase === 'discover' && ($strategy === '' || ! $config->hasStrategy($strategy))) {
            throw ActionFailed::badRequest(['detail' => "Unknown discover strategy: {$strategy}"]);
        }

        $existing = $this->runs->activeRunForShop($shop->id);
        if ($existing instanceof ScrapeRun) {
            throw ActionFailed::conflict([
                'detail' => "A {$existing->phase} run for {$shop->name} is already "
                    ."{$existing->status} (run #{$existing->id}).",
            ]);
        }
    }

    private function spawnRequest(RunLaunchRequest $request): void
    {
        try {
            $this->launcher->spawnRequest($request);
        } catch (Throwable $e) {
            throw ActionFailed::unavailable(['detail' => $e->getMessage()]);
        }
    }

    private function spawn(
        string $phase,
        string $shop,
        string $strategy = '',
        ?int $adoptRunId = null,
    ): void {
        try {
            $this->launcher->spawn($phase, $shop, $strategy, adoptRunId: $adoptRunId);
        } catch (Throwable $e) {
            throw ActionFailed::unavailable(['detail' => $e->getMessage()]);
        }
    }

    /** @return array{string, string} */
    private function splitPhase(string $phase): array
    {
        if (str_starts_with($phase, 'discover_')) {
            return ['discover', substr($phase, strlen('discover_'))];
        }

        return [$phase, ''];
    }
}
