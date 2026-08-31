<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\Request\RunQueryInput;
use App\Models\ScrapeRun;

final readonly class RunReadRepository
{
    public function __construct(
        private RunListReadRepository $list = new RunListReadRepository,
        private RunDetailReadRepository $details = new RunDetailReadRepository,
    ) {}

    /** @return array<string, mixed> */
    public function index(RunQueryInput $input): array
    {
        return $this->list->index($input);
    }

    /** @return array<string, mixed> */
    public function show(ScrapeRun $run): array
    {
        return $this->details->show($run);
    }

    /** @return array<string, mixed> */
    public function books(RunQueryInput $input, ScrapeRun $run): array
    {
        return $this->details->books($input, $run);
    }
}
