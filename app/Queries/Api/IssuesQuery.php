<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\DTO\Request\IssueQueryInput;
use App\Models\ValidationIssue;
use App\Repositories\IssueReadRepository;
use stdClass;

final readonly class IssuesQuery
{
    public function __construct(private IssueReadRepository $issues) {}

    /** @return array<string, mixed> */
    public function index(IssueQueryInput $input): array
    {
        return $this->issues->index($input);
    }

    /** @return array<string, mixed> */
    public function groups(IssueQueryInput $input): array
    {
        return $this->issues->groups($input);
    }

    /** @return array<string, list<int>>|stdClass */
    public function trend(IssueQueryInput $input): array|stdClass
    {
        return $this->issues->trend($input);
    }

    /** @return array<string, mixed> */
    public function show(ValidationIssue $issue): array
    {
        return $this->issues->show($issue);
    }
}
