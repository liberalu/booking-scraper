<?php

declare(strict_types=1);

namespace App\Exceptions;

use RuntimeException;

final class ActionFailed extends RuntimeException
{
    /** @param array<string, mixed> $payload */
    private function __construct(
        public readonly array $payload,
        public readonly FailureKind $kind,
    ) {
        parent::__construct('Application action failed.');
    }

    /** @param array<string, mixed> $payload */
    public static function badRequest(array $payload): self
    {
        return new self($payload, FailureKind::BadRequest);
    }

    /** @param array<string, mixed> $payload */
    public static function conflict(array $payload): self
    {
        return new self($payload, FailureKind::Conflict);
    }

    /** @param array<string, mixed> $payload */
    public static function notFound(array $payload): self
    {
        return new self($payload, FailureKind::NotFound);
    }

    /** @param array<string, mixed> $payload */
    public static function payloadTooLarge(array $payload): self
    {
        return new self($payload, FailureKind::PayloadTooLarge);
    }

    /** @param array<string, mixed> $payload */
    public static function unavailable(array $payload): self
    {
        return new self($payload, FailureKind::Unavailable);
    }

    /** @param array<string, mixed> $payload */
    public static function unprocessable(array $payload): self
    {
        return new self($payload, FailureKind::Unprocessable);
    }
}
