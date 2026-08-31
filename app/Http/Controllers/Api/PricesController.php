<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Http\Requests\PriceQueryRequest;
use App\Queries\Api\PricesQuery;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class PricesController
{
    public function __construct(private PricesQuery $query) {}

    public function __invoke(PriceQueryRequest $request): JsonResponse
    {
        return new JsonResponse(($this->query)($request->toDto()), Response::HTTP_OK);
    }
}
