<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\IssueMutationRequest;
use App\Models\ValidationIssue;
use App\Services\Issues\IssueMutationsService;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class IssueMutationsController
{
    public function __construct(private IssueMutationsService $service) {}

    public function lifecycle(IssueMutationRequest $request, ValidationIssue $issue): JsonResponse
    {
        return new JsonResponse(
            $this->service->lifecycle($request->toDto(), $issue),
            Response::HTTP_OK,
        );
    }

    public function snooze(IssueMutationRequest $request, ValidationIssue $issue): JsonResponse
    {
        return new JsonResponse(
            $this->service->snooze($request->toDto(), $issue),
            Response::HTTP_OK,
        );
    }

    public function bulkAcknowledge(IssueMutationRequest $request): JsonResponse
    {
        return new JsonResponse(
            $this->service->bulkAcknowledge($request->toDto()),
            Response::HTTP_OK,
        );
    }

    public function bulkUnacknowledge(IssueMutationRequest $request): JsonResponse
    {
        return new JsonResponse(
            $this->service->bulkUnacknowledge($request->toDto()),
            Response::HTTP_OK,
        );
    }

    public function bulkRescrape(IssueMutationRequest $request): JsonResponse
    {
        return new JsonResponse(
            $this->service->bulkRescrape($request->toDto()),
            Response::HTTP_OK,
        );
    }
}
