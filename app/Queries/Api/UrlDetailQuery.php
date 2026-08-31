<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\Models\DiscoveredUrl;
use App\Repositories\UrlDetailReadRepository;

final readonly class UrlDetailQuery
{
    public function __construct(private UrlDetailReadRepository $urls) {}

    /** @return array<string, mixed> */
    public function __invoke(DiscoveredUrl $url): array
    {
        return ($this->urls)($url);
    }
}
