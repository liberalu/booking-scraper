<?php

declare(strict_types=1);

namespace App\Contracts;

use App\Runs\RunLaunchRequest;

interface RunLauncher
{
    /** @return array{log: string, pid: int|null, cmd: list<string>} */
    public function spawn(
        string $phase,
        string $shop,
        string $strategy = '',
        string $mode = 'delta',
        string $urls = '',
        ?int $cronJobId = null,
        string $role = 'operator',
        ?int $adoptRunId = null,
    ): array;

    /** @return array{log: string, pid: int|null, cmd: list<string>} */
    public function spawnRequest(RunLaunchRequest $request): array;
}
