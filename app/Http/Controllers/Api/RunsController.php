<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\RunQueryRequest;
use App\Models\ScrapeRun;
use App\Queries\Api\RunsQuery;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class RunsController
{
    public function __construct(private RunsQuery $query) {}

    public function index(RunQueryRequest $request): JsonResponse
    {
        return new JsonResponse($this->query->index($request->toDto()), Response::HTTP_OK);
    }

    public function show(ScrapeRun $run): JsonResponse
    {
        return new JsonResponse($this->query->show($run), Response::HTTP_OK);
    }

    public function books(RunQueryRequest $request, ScrapeRun $run): JsonResponse
    {
        return new JsonResponse(
            $this->query->books($request->toDto(), $run),
            Response::HTTP_OK,
        );
    }
}
