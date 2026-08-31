<?php

declare(strict_types=1);

namespace App\DTO\Request;

final readonly class RunMutationInput
{
    public function __construct(
        public string $phase,
        public string $shop,
        public string $strategy,
        public string $mode,
        public string $urls,
        public ?int $cronJobId,
        public string $errorReason,
        public bool $errorReasonIsNull,
        public ?int $httpStatus,
        public bool $httpStatusIsNull,
        public string $note,
    ) {}
}
