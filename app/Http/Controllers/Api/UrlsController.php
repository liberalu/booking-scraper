<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\UrlQueryRequest;
use App\Queries\Api\UrlsQuery;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class UrlsController
{
    public function __construct(private UrlsQuery $query) {}

    public function index(UrlQueryRequest $request): JsonResponse
    {
        return new JsonResponse($this->query->index($request->toDto()), Response::HTTP_OK);
    }
}
