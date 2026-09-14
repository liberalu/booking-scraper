<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Repositories\CanonicalBookRepository;
use App\Repositories\CrawlerQueueRepository;
use App\Repositories\DiscoveredUrlRepository;
use App\Runs\ProgressReporter;
use InvalidArgumentException;
use Throwable;

final class CrawlerContext
{
    private ?Persister $persister = null;

    private DiscoveredUrlRepository $urls;

    private CanonicalBookRepository $canonical;

    private readonly CrawlerQueueRepository $queue;

    private ?ProgressReporter $progress = null;

    private int $shopId = 0;

    private ?int $runId = null;

    private ?Watchdog $watchdog = null;

    private int $filtered;

    /** @var array<string, true> */
    private array $seen = [];

    private int $added;

    private int $updated;

    private int $urlCount;

    private int $nonProduct;

    private int $canonicalCount;

    private int $failed;

    public function __construct(private readonly IssueBuffer $issues = new IssueBuffer)
    {
        $this->urls = new DiscoveredUrlRepository;
        $this->canonical = new CanonicalBookRepository;
        $this->queue = new CrawlerQueueRepository;
        $this->reset();
    }

    public function issues(): IssueBuffer
    {
        return $this->issues;
    }

    public function bind(
        Persister $persister,
        int $shopId,
        ?int $runId,
        ?DiscoveredUrlRepository $urls = null,
        ?ProgressReporter $progress = null,
    ): void {
        $this->persister = $persister;
        $this->urls = $urls ?? new DiscoveredUrlRepository;
        $this->canonical = new CanonicalBookRepository;
        $this->progress = $progress;
        $this->shopId = $shopId;
        $this->runId = $runId;
        $this->reset();
    }

    public function reset(): void
    {
        $this->added = 0;
        $this->updated = 0;
        $this->urlCount = 0;
        $this->nonProduct = 0;
        $this->canonicalCount = 0;
        $this->failed = 0;
        $this->filtered = 0;
        $this->seen = [];
        $this->issues->reset();
    }

    /** @return array{added: int, updated: int, urls: int, non_product: int, canonical: int, failed: int} */
    public function tally(): array
    {
        return [
            'added' => $this->added,
            'updated' => $this->updated,
            'urls' => $this->urlCount,
            'non_product' => $this->nonProduct,
            'canonical' => $this->canonicalCount,
            'failed' => $this->failed,
        ];
    }

    public function increment(string $key): void
    {
        match ($key) {
            'added' => $this->added++,
            'updated' => $this->updated++,
            'urls' => $this->urlCount++,
            'non_product' => $this->nonProduct++,
            'canonical' => $this->canonicalCount++,
            'failed' => $this->failed++,
            default => throw new InvalidArgumentException("Unknown crawler tally: {$key}"),
        };
    }

    public function tick(): void
    {
        $this->progress?->tick($this->tally());
    }

    public function persister(): ?Persister
    {
        return $this->persister;
    }

    public function urls(): DiscoveredUrlRepository
    {
        return $this->urls;
    }

    public function canonical(): CanonicalBookRepository
    {
        return $this->canonical;
    }

    public function shopId(): int
    {
        return $this->shopId;
    }

    public function runId(): ?int
    {
        return $this->runId;
    }

    public function markFetched(string $url, ?int $httpStatus = null, ?int $responseBytes = null): void
    {
        if ($this->runId === null) {
            return;
        }

        try {
            $this->queue->markDone($this->runId, $url, $httpStatus, $responseBytes);
        } catch (Throwable $e) {
            fwrite(STDERR, sprintf("  queue update failed  %s  %s\n", $url, $e->getMessage()));
        }
    }

    public function markFetchFailed(string $url, string $reason, ?int $httpStatus = null, ?string $detail = null): void
    {
        if ($this->runId === null) {
            return;
        }

        try {
            $this->queue->markFailed($this->runId, $url, $reason, $httpStatus, $detail);
            if ($reason !== 'persist_error' && $this->shopId > 0) {
                $this->urls->recordFetchFailure($this->shopId, $url, $httpStatus, $this->runId);
            }
        } catch (Throwable $e) {
            fwrite(STDERR, sprintf("  queue update failed  %s  %s\n", $url, $e->getMessage()));
        }
    }

    public function bindWatchdog(?Watchdog $watchdog): void
    {
        $this->watchdog = $watchdog;
    }

    public function recordActivity(): void
    {
        $this->watchdog?->recordActivity();
    }

    public function incrementFiltered(): void
    {
        $this->filtered++;
    }

    public function filteredCount(): int
    {
        return $this->filtered;
    }

    public function seenCount(): int
    {
        return count($this->seen);
    }

    public function remember(string $url): bool
    {
        if (isset($this->seen[$url])) {
            return false;
        }
        $this->seen[$url] = true;

        return true;
    }
}
