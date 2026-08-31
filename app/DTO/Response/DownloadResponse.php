<?php

declare(strict_types=1);

namespace App\DTO\Response;

use Closure;

final readonly class DownloadResponse
{
    /** @param array<string, string> $headers */
    public function __construct(
        public Closure $writer,
        public string $filename,
        public array $headers = [],
    ) {}
}
