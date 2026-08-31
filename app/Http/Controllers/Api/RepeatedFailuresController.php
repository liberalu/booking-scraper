<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Queries\Api\RepeatedFailuresQuery;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class RepeatedFailuresController
{
    public function __construct(private RepeatedFailuresQuery $query) {}

    public function __invoke(): JsonResponse
    {
        return new JsonResponse(($this->query)(), Response::HTTP_OK);
    }
}
