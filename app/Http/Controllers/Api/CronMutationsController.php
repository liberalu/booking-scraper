<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\CronMutationRequest;
use App\Models\CronJob;
use App\Services\Scheduling\CronMutationsService;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class CronMutationsController
{
    public function __construct(private CronMutationsService $service) {}

    public function store(CronMutationRequest $request): JsonResponse
    {
        return new JsonResponse($this->service->store($request->toDto()), Response::HTTP_OK);
    }

    public function update(CronMutationRequest $request, CronJob $job): JsonResponse
    {
        return new JsonResponse(
            $this->service->update($request->toDto(), $job),
            Response::HTTP_OK,
        );
    }

    public function destroy(CronJob $job): JsonResponse
    {
        return new JsonResponse($this->service->destroy($job), Response::HTTP_OK);
    }

    public function toggle(CronJob $job): JsonResponse
    {
        return new JsonResponse($this->service->toggle($job), Response::HTTP_OK);
    }
}
