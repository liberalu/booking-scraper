<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Models\Shop;
use App\Queries\Api\ShopsQuery;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class ShopsController
{
    public function __construct(private ShopsQuery $query) {}

    public function index(): JsonResponse
    {
        return new JsonResponse($this->query->index(), Response::HTTP_OK);
    }

    public function show(Shop $shop): JsonResponse
    {
        return new JsonResponse($this->query->show($shop), Response::HTTP_OK);
    }
}
