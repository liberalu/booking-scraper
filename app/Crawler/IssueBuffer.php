<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Repositories\ValidationIssueRepository;
use App\Support\Database;
use Throwable;

/** @phpstan-import-type BufferedIssue from CrawlerTypes */
final class IssueBuffer
{
    /** @var list<BufferedIssue> */
    private array $issues = [];

    public function reset(): void
    {
        $this->issues = [];
    }

    public function add(
        string $issue,
        string $field,
        string $url,
        string $rawValue = '',
    ): void {
        $this->issues[] = [
            'url' => $url,
            'field' => $field,
            'issue' => $issue,
            'raw_value' => $rawValue === '' ? null : $rawValue,
        ];
        fwrite(STDERR, sprintf(
            "  validation [%s] field=%s url=%s %s\n",
            $issue,
            $field,
            $url,
            $rawValue
        ));
    }

    /** @return list<BufferedIssue> */
    public function drain(): array
    {
        $issues = $this->issues;
        $this->issues = [];

        return $issues;
    }

    public function count(): int
    {
        return count($this->issues);
    }

    public function flush(int $shopId, int $runId): int
    {
        $issues = $this->drain();
        if ($issues === []) {
            return 0;
        }
        try {
            (new ValidationIssueRepository(Database::manager()))->upsert($issues, $shopId, $runId);

            return count($issues);
        } catch (Throwable $e) {
            fwrite(STDERR, "  could not write validation issues: {$e->getMessage()}\n");

            return 0;
        }
    }
}
