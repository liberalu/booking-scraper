<?php

declare(strict_types=1);

namespace Tests\Support;

use App\Contracts\RunLauncher;
use App\Runs\RunLaunchRequest;
use LogicException;

final readonly class RecordingLauncher implements RunLauncher
{
    public function __construct(private string $record) {}

    public function spawn(
        string $phase,
        string $shop,
        string $strategy = '',
        string $mode = 'delta',
        string $urls = '',
        ?int $cronJobId = null,
        string $role = 'operator',
        ?int $adoptRunId = null,
    ): array {
        throw new LogicException('the watchdog builds a request, it does not call spawn()');
    }

    public function spawnRequest(RunLaunchRequest $request): array
    {
        file_put_contents($this->record, json_encode([
            'phase' => $request->phase->value,
            'shop' => $request->shop,
            'strategy' => $request->strategy,
            'role' => $request->role,
            'adoptRunId' => $request->adoptRunId,
        ], JSON_THROW_ON_ERROR));

        return ['log' => $this->record, 'pid' => 1, 'cmd' => []];
    }
}
