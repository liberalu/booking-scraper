<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Queries\Api\ScheduleQuery;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class ScheduleController
{
    public function __construct(private ScheduleQuery $query) {}

    public function __invoke(): JsonResponse
    {
        return new JsonResponse(($this->query)(), Response::HTTP_OK);
    }
}
