<?php

declare(strict_types=1);

namespace App\Crawler;

/**
 * @phpstan-type ParsedItem array<string, mixed>
 * @phpstan-type AttributeSchema array{allowed_keys: list<string>, rules: array<string, array<string, mixed>>}
 * @phpstan-type ItemPayload array{data: array<string, mixed>, properties: array<string, mixed>|null}
 * @phpstan-type BufferedIssue array{url: string, field: string, issue: string, raw_value: string|null}
 * @phpstan-type FlareResponse array{status: int, body: string, url: string, headers: array<string, string>}
 * @phpstan-type BookScoreReason array{key: string, points: int}
 * @phpstan-type DiscoveryResult array{products: list<ParsedItem>, total: int|null}
 */
final class CrawlerTypes {}
