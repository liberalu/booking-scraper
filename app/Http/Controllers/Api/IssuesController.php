<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\IssueQueryRequest;
use App\Models\ValidationIssue;
use App\Queries\Api\IssuesQuery;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class IssuesController
{
    public function __construct(private IssuesQuery $query) {}

    public function index(IssueQueryRequest $request): JsonResponse
    {
        return new JsonResponse($this->query->index($request->toDto()), Response::HTTP_OK);
    }

    public function groups(IssueQueryRequest $request): JsonResponse
    {
        return new JsonResponse($this->query->groups($request->toDto()), Response::HTTP_OK);
    }

    public function trend(IssueQueryRequest $request): JsonResponse
    {
        return new JsonResponse($this->query->trend($request->toDto()), Response::HTTP_OK);
    }

    public function show(ValidationIssue $issue): JsonResponse
    {
        return new JsonResponse($this->query->show($issue), Response::HTTP_OK);
    }
}
