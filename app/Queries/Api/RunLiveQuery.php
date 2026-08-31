<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\DTO\Request\RunQueryInput;
use App\Models\ScrapeRun;
use App\Repositories\RunLiveReadRepository;

final readonly class RunLiveQuery
{
    public function __construct(private RunLiveReadRepository $runs) {}

    /** @return array<string, mixed> */
    public function __invoke(RunQueryInput $input, ScrapeRun $run): array
    {
        return ($this->runs)($input, $run);
    }
}
