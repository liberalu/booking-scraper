<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\RunMutationRequest;
use App\Models\ScrapeRun;
use App\Services\Runs\RunMutationsService;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class RunMutationsController
{
    public function __construct(private RunMutationsService $service) {}

    public function stop(ScrapeRun $run): JsonResponse
    {
        return new JsonResponse($this->service->stop($run), Response::HTTP_OK);
    }

    public function pause(ScrapeRun $run): JsonResponse
    {
        return new JsonResponse($this->service->pause($run), Response::HTTP_OK);
    }

    public function resume(ScrapeRun $run): JsonResponse
    {
        return new JsonResponse($this->service->resume($run), Response::HTTP_OK);
    }

    public function ackFailures(RunMutationRequest $request, ScrapeRun $run): JsonResponse
    {
        return new JsonResponse(
            $this->service->ackFailures($request->toDto(), $run),
            Response::HTTP_OK,
        );
    }
}
