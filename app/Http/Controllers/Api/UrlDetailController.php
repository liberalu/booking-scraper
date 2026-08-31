<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Models\DiscoveredUrl;
use App\Queries\Api\UrlDetailQuery;
use Illuminate\Http\JsonResponse;
use Symfony\Component\HttpFoundation\Response;

final readonly class UrlDetailController
{
    public function __construct(private UrlDetailQuery $query) {}

    public function __invoke(DiscoveredUrl $url): JsonResponse
    {
        return new JsonResponse(($this->query)($url), Response::HTTP_OK);
    }
}
