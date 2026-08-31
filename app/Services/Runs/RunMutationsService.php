<?php

declare(strict_types=1);

namespace App\Services\Runs;

use App\DTO\Request\RunMutationInput;
use App\Exceptions\ActionFailed;
use App\Models\ScrapeRun;
use App\Repositories\ScrapeRunRepository;

final readonly class RunMutationsService
{
    public function __construct(private ScrapeRunRepository $runs) {}

    /** @return array{run_id: int, status: string} */
    public function stop(ScrapeRun $run): array
    {
        $runId = $run->id;

        if (in_array($run->status, ['running', 'paused'], true)) {
            $this->runs->requestStop($run);

            return ['run_id' => $runId, 'status' => 'stopping'];
        }

        return ['run_id' => $runId, 'status' => $run->status];
    }

    /** @return array{run_id: int, status: string} */
    public function pause(ScrapeRun $run): array
    {
        $runId = $run->id;
        if ($run->status === 'running') {
            $this->runs->pause($run);

            return ['run_id' => $runId, 'status' => 'paused'];
        }

        return ['run_id' => $runId, 'status' => $run->status];
    }

    /** @return array{run_id: int, status: string} */
    public function resume(ScrapeRun $run): array
    {
        $runId = $run->id;
        if ($run->status === 'paused') {
            $this->runs->resume($run);

            return ['run_id' => $runId, 'status' => 'running'];
        }

        return ['run_id' => $runId, 'status' => $run->status];
    }

    /** @return array{acknowledged: int, run_id: int, error_reason: string|null, http_status: int|null} */
    public function ackFailures(RunMutationInput $input, ScrapeRun $run): array
    {
        $runId = $run->id;
        $errorReason = $input->errorReason;
        $reasonIsNull = $input->errorReasonIsNull;
        $httpStatus = $input->httpStatus;
        $statusIsNull = $input->httpStatusIsNull;
        $note = $input->note;

        $status = $httpStatus;
        $matches = $this->runs->acknowledgeFailures(
            $run,
            $errorReason,
            $reasonIsNull,
            $status,
            $statusIsNull,
            $note,
        );
        if ($matches === 0) {
            throw ActionFailed::badRequest([
                'detail' => 'No matching scrape_failures rows to acknowledge.',
            ]);
        }

        return [
            'acknowledged' => $matches,
            'run_id' => $runId,
            'error_reason' => $reasonIsNull || $errorReason === '' ? null : $errorReason,
            'http_status' => $statusIsNull ? null : $httpStatus,
        ];
    }
}
