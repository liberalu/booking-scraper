<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\RunMutationRequest;
use App\Models\ScrapeRun;
use App\Services\Runs\RunSpawnService;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class RunSpawnController
{
    public function __construct(private RunSpawnService $service) {}

    public function store(RunMutationRequest $request): JsonResponse
    {
        return new JsonResponse($this->service->store($request->toDto()), Response::HTTP_OK);
    }

    public function rerun(ScrapeRun $run): JsonResponse
    {
        return new JsonResponse($this->service->rerun($run), Response::HTTP_OK);
    }

    public function continueRun(ScrapeRun $run): JsonResponse
    {
        return new JsonResponse($this->service->continueRun($run), Response::HTTP_OK);
    }

    public function retry(RunMutationRequest $request, ScrapeRun $run): JsonResponse
    {
        return new JsonResponse(
            $this->service->retry($request->toDto(), $run),
            Response::HTTP_OK,
        );
    }
}
