<?php

declare(strict_types=1);

namespace App\DTO\Request;

final readonly class RunQueryInput
{
    public function __construct(
        public ?string $shop,
        public ?string $phase,
        public ?string $status,
        public ?string $when,
        public string $search,
        public ?int $page,
        public ?int $perPage,
        public ?string $type,
        public ?string $sort,
        public ?string $order,
        public string $errorReason,
        public bool $errorReasonIsNull,
        public ?int $httpStatus,
        public bool $httpStatusIsNull,
        public bool $includeAcknowledged,
        public string $note,
    ) {}
}
