<?php

declare(strict_types=1);

namespace App\Runs;

use InvalidArgumentException;

final readonly class RunLaunchRequest
{
    public function __construct(
        public RunPhase $phase,
        public string $shop,
        public string $strategy = '',
        public string $mode = 'delta',
        public string $urls = '',
        public ?int $cronJobId = null,
        public string $role = 'operator',
        public ?int $adoptRunId = null,
    ) {
        if ($this->shop === '') {
            throw new InvalidArgumentException('A shop is required to launch a run');
        }
        if (! in_array($this->mode, ['delta', 'full', 'sample'], true)) {
            throw new InvalidArgumentException("Unknown scan mode: {$this->mode}");
        }
        if ($this->adoptRunId !== null && $this->phase !== RunPhase::Scan) {
            throw new InvalidArgumentException('Only scan runs can adopt an existing queue');
        }
        if ($this->adoptRunId !== null && $this->urls !== '') {
            throw new InvalidArgumentException('An adopted queue cannot be combined with explicit URLs');
        }
        if ($this->urls !== '' && $this->mode !== 'delta') {
            throw new InvalidArgumentException('Explicit URLs cannot be combined with a scan mode');
        }
        if ($this->strategy !== '' && $this->phase !== RunPhase::Discover) {
            throw new InvalidArgumentException('A discovery strategy only applies to discover runs');
        }
    }
}
