<?php

declare(strict_types=1);

namespace App\Queries\Api;

use App\DTO\Request\UrlQueryInput;
use App\Repositories\UrlReadRepository;

final readonly class UrlsQuery
{
    public function __construct(private UrlReadRepository $urls) {}

    /** @return array<string, mixed> */
    public function index(UrlQueryInput $input): array
    {
        return $this->urls->index($input);
    }
}
