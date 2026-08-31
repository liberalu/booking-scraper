<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\DTO\Request\RunQueryInput;
use App\Models\ScrapeRun;
use App\Repositories\RunReadRepository;

final readonly class RunsQuery
{
    public function __construct(private RunReadRepository $runs) {}

    /** @return array<string, mixed> */
    public function index(RunQueryInput $input): array
    {
        return $this->runs->index($input);
    }

    /** @return array<string, mixed> */
    public function show(ScrapeRun $run): array
    {
        return $this->runs->show($run);
    }

    /** @return array<string, mixed> */
    public function books(RunQueryInput $input, ScrapeRun $run): array
    {
        return $this->runs->books($input, $run);
    }
}
