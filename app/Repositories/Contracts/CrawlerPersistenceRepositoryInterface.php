<?php

declare(strict_types=1);

namespace App\Repositories\Contracts;

use App\Repositories\UpsertResult;
use Closure;

interface CrawlerPersistenceRepositoryInterface
{
    /**
     * @template T
     *
     * @param  Closure(): T  $operation
     * @return T
     */
    public function transaction(Closure $operation): mixed;

    /** @param array<string, mixed> $data */
    public function appendPrice(UpsertResult $result, array $data, ?int $runId): bool;

    public function recordChanges(UpsertResult $result, ?int $runId): void;
}
