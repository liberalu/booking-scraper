<?php

declare(strict_types=1);

namespace BookScraper\Crawler;

use BookScraper\Services\ValidationIssueWriter;
use Throwable;

/**
 * Data-quality issues noticed while crawling, held until the run closes.
 *
 * The validator phase finds problems by querying stored rows; these are the
 * ones only the crawl can see — a page that came back empty, a redirect to the
 * homepage, an ISBN that failed its checksum before being discarded. Upstream
 * buffers them on the pipeline and flushes once at spider close, so a run
 * writes issues in one batch rather than a row at a time.
 *
 * Static because roach builds processors through its container: the CLI has no
 * seam to inject into.
 */
final class IssueBuffer
{
    /** @var list<array{url: string, field: string, issue: string, raw_value: string|null}> */
    private static array $issues = [];

    public static function reset(): void
    {
        self::$issues = [];
    }

    public static function add(
        string $issue,
        string $field,
        string $url,
        string $rawValue = '',
    ): void {
        self::$issues[] = [
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

    /** @return list<array{url: string, field: string, issue: string, raw_value: string|null}> */
    public static function drain(): array
    {
        $issues = self::$issues;
        self::$issues = [];

        return $issues;
    }

    public static function count(): int
    {
        return count(self::$issues);
    }

    /**
     * Write what the crawl noticed.
     *
     * Swallows failures on purpose: a crawl that fetched and stored everything
     * correctly must not be reported as failed because its issue batch could
     * not be written.
     */
    public static function flush(int $shopId, int $runId): int
    {
        $issues = self::drain();
        if ($issues === []) {
            return 0;
        }
        try {
            (new ValidationIssueWriter())->upsert($issues, $shopId, $runId);

            return count($issues);
        } catch (Throwable $e) {
            fwrite(STDERR, "  could not write validation issues: {$e->getMessage()}\n");

            return 0;
        }
    }
}
