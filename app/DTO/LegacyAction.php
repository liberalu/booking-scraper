<?php

declare(strict_types=1);

namespace App\DTO;

use LogicException;

final readonly class LegacyAction
{
    /** @param array<string, mixed>|string $payload */
    private function __construct(
        public LegacyActionKind $kind,
        public array|string $payload,
    ) {}

    /** @param array<string, mixed> $payload */
    public static function accepted(array $payload): self
    {
        return new self(LegacyActionKind::Accepted, $payload);
    }

    public static function html(string $content): self
    {
        return new self(LegacyActionKind::Html, $content);
    }

    public static function redirect(string $url): self
    {
        return new self(LegacyActionKind::Redirect, $url);
    }

    public function stringPayload(): string
    {
        if (! is_string($this->payload)) {
            throw new LogicException('This legacy action does not contain a string payload.');
        }

        return $this->payload;
    }
}
