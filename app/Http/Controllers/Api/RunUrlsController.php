<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\RunQueryRequest;
use App\Models\ScrapeRun;
use App\Queries\Api\RunUrlsQuery;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class RunUrlsController
{
    public function __construct(private RunUrlsQuery $query) {}

    public function __invoke(RunQueryRequest $request, ScrapeRun $run): JsonResponse
    {
        return new JsonResponse(
            ($this->query)($request->toDto(), $run),
            Response::HTTP_OK,
        );
    }
}
