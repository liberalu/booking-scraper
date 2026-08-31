<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\DTO\Request\RunQueryInput;
use App\Models\ScrapeRun;
use App\Repositories\RunUrlReadRepository;

final readonly class RunUrlsQuery
{
    public function __construct(private RunUrlReadRepository $urls) {}

    /** @return array<string, mixed> */
    public function __invoke(RunQueryInput $input, ScrapeRun $run): array
    {
        return ($this->urls)($input, $run);
    }
}
