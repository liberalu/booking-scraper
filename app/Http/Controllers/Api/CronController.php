<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Models\CronJob;
use App\Queries\Api\CronQuery;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class CronController
{
    public function __construct(private CronQuery $query) {}

    public function index(): JsonResponse
    {
        return new JsonResponse($this->query->index(), Response::HTTP_OK);
    }

    public function show(CronJob $job): JsonResponse
    {
        return new JsonResponse($this->query->show($job), Response::HTTP_OK);
    }
}
