<?php

declare(strict_types=1);

namespace App\Services\Scheduling;

use App\DTO\Request\CronMutationInput;
use App\Exceptions\ActionFailed;
use App\Models\CronJob;
use App\Models\Shop;
use App\Repositories\CronJobRepository;
use App\Support\Config;
use Cron\CronExpression;
use RuntimeException;

final readonly class CronMutationsService
{
    private const array PHASES = ['discover', 'scan'];

    public function __construct(private CronJobRepository $jobs) {}

    /** @return array{id: int, name: string} */
    public function store(CronMutationInput $input): array
    {
        $shop = $this->jobs->shopByName($input->shop);
        if (! $shop instanceof Shop) {
            throw ActionFailed::notFound(['detail' => 'Shop not found']);
        }
        $phase = $input->phase ?? '';
        if (! in_array($phase, self::PHASES, true)) {
            throw ActionFailed::unprocessable(['detail' => "phase must be 'discover' or 'scan'"]);
        }
        $expression = $input->cronExpression ?? '';
        if (($bad = $this->cronError($expression)) !== null) {
            throw ActionFailed::unprocessable(['detail' => $bad]);
        }

        $chainToId = $input->chainToId;
        if ($chainToId !== null && ! $this->jobs->find($chainToId) instanceof CronJob) {
            throw ActionFailed::notFound(['detail' => 'Chain target job not found']);
        }

        $trimmedStrategy = trim($input->strategy ?? '');
        $strategy = $trimmedStrategy !== '' ? $trimmedStrategy : null;
        $this->validateStrategy($shop->name, $phase, $strategy);
        $job = $this->jobs->create($shop, $phase, $strategy, $expression, $chainToId);

        return [
            'id' => $job->id,
            'name' => "{$shop->name}.{$job->phase}.".($strategy ?? 'default'),
        ];
    }

    /** @return array{id: int} */
    public function update(CronMutationInput $input, CronJob $job): array
    {
        $jobId = $job->id;

        $expression = $input->cronExpression;
        if ($expression !== null && ($bad = $this->cronError($expression)) !== null) {
            throw ActionFailed::unprocessable(['detail' => $bad]);
        }

        $fields = [];
        if ($expression !== null) {
            $fields['cron_expression'] = $expression;
        }

        $phase = $input->phase;
        if ($phase !== null) {
            if (! in_array($phase, self::PHASES, true)) {
                throw ActionFailed::unprocessable(['detail' => "phase must be 'discover' or 'scan'"]);
            }
            $fields['phase'] = $phase;
        }

        $strategy = $input->strategy;
        if ($strategy !== null) {
            $trimmedStrategy = trim($strategy);
            $fields['strategy'] = $trimmedStrategy !== '' ? $trimmedStrategy : null;
        }

        $effectivePhase = is_string($fields['phase'] ?? null) ? $fields['phase'] : $job->phase;
        $effectiveStrategy = array_key_exists('strategy', $fields)
            ? (is_string($fields['strategy']) ? $fields['strategy'] : null)
            : $job->strategy;
        if ($effectivePhase === 'scan') {
            $effectiveStrategy = null;
            $fields['strategy'] = null;
        }
        if (array_key_exists('phase', $fields) || array_key_exists('strategy', $fields)) {
            $job->loadMissing('shop');
            $this->validateStrategy($job->shop->name, $effectivePhase, $effectiveStrategy);
        }

        $chainToId = $input->chainToId;
        $clearChain = $input->clearChain;
        if ($chainToId !== null && $clearChain) {
            throw ActionFailed::unprocessable([
                'detail' => 'Provide chain_to_id or clear_chain, not both',
            ]);
        }
        if ($chainToId !== null) {
            if ($chainToId === $jobId) {
                throw ActionFailed::unprocessable(['detail' => 'A job cannot chain to itself']);
            }
            if (! $this->jobs->find($chainToId) instanceof CronJob) {
                throw ActionFailed::notFound(['detail' => 'Chain target job not found']);
            }
            if ($this->wouldCycle($jobId, $chainToId)) {
                throw ActionFailed::unprocessable(['detail' => 'Chain would create a cycle']);
            }
            $fields['chain_to_job_id'] = $chainToId;
        } elseif ($clearChain) {
            $fields['chain_to_job_id'] = null;
        }

        if ($fields !== []) {
            $this->jobs->update($job, $fields);
        }

        return ['id' => $jobId];
    }

    /** @return array{id: int} */
    public function destroy(CronJob $job): array
    {
        $jobId = $job->id;
        $dependents = $this->jobs->dependents($job);

        if ($dependents !== []) {
            throw ActionFailed::conflict([
                'detail' => [
                    'message' => 'Cannot delete: other schedules chain to this one.',
                    'dependents' => $dependents,
                ],
            ]);
        }

        $this->jobs->delete($job);

        return ['id' => $jobId];
    }

    /** @return array{id: int, enabled: bool} */
    public function toggle(CronJob $job): array
    {
        $jobId = $job->id;
        $enabled = ! $job->enabled;
        $this->jobs->update($job, ['enabled' => $enabled]);

        return ['id' => $jobId, 'enabled' => $enabled];
    }

    private function cronError(string $expression): ?string
    {
        $trimmed = trim($expression);
        $parsedFields = preg_split('/\s+/', $trimmed, -1, PREG_SPLIT_NO_EMPTY);
        $fields = $parsedFields !== false ? $parsedFields : [];
        if (count($fields) !== 5 || ! CronExpression::isValidExpression($trimmed)) {
            return 'Invalid cron expression: '.$this->pyRepr($expression)
                .' (expected 5 fields)';
        }

        return null;
    }

    private function validateStrategy(string $shop, string $phase, ?string $strategy): void
    {
        if ($phase === 'scan') {
            if ($strategy !== null) {
                throw ActionFailed::unprocessable(['detail' => 'Scan schedules cannot have a strategy']);
            }

            return;
        }

        try {
            $configured = $strategy !== null && Config::forShop($shop)->hasStrategy($strategy);
        } catch (RuntimeException) {
            throw ActionFailed::unprocessable([
                'detail' => "Shop is not configured for crawling: {$shop}",
            ]);
        }

        if (! $configured) {
            throw ActionFailed::unprocessable([
                'detail' => "Unknown discover strategy for {$shop}: ".($strategy ?? '(missing)'),
            ]);
        }
    }

    private function wouldCycle(int $jobId, int $chainToId): bool
    {
        $visited = [];
        $next = $chainToId;
        while ($next !== null) {
            if ($next === $jobId) {
                return true;
            }
            if (isset($visited[$next])) {
                break;
            }
            $visited[$next] = true;
            $job = $this->jobs->find($next);
            if (! $job instanceof CronJob) {
                break;
            }
            $next = $job->chain_to_job_id;
        }

        return false;
    }

    private function pyRepr(string $value): string
    {
        if (! str_contains($value, "'")) {
            return "'".str_replace('\\', '\\\\', $value)."'";
        }
        if (! str_contains($value, '"')) {
            return '"'.str_replace('\\', '\\\\', $value).'"';
        }

        return "'".str_replace(['\\', "'"], ['\\\\', "\\'"], $value)."'";
    }
}
