<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Repositories\CanonicalBookRepository;
use App\Repositories\CrawlerQueueRepository;
use App\Runs\ProgressReporter;
use App\Support\Config;
use App\Support\ParserRegistry;
use Illuminate\Support\Sleep;
use RuntimeException;
use Throwable;

final readonly class SerialScanner
{
    public function __construct(
        private string $shop,
        private Config $config,
        private Persister $persister,
        private int $shopId,
        private ?int $runId,
        private ?Watchdog $watchdog = null,
        private CanonicalBookRepository $canonical = new CanonicalBookRepository,
        private ProgressReporter $progress = new ProgressReporter,
        private CrawlerQueueRepository $queue = new CrawlerQueueRepository,
    ) {}

    /**
     * @param  iterable<string>  $urls
     * @return array{added: int, updated: int, canonical: int, non_product: int, failed: int}
     */
    public function run(iterable $urls): array
    {
        $fsConfig = $this->config->flaresolverr();
        if ($fsConfig === null) {
            throw new RuntimeException("shop {$this->shop} has no [flaresolverr] block");
        }

        $flareSolverr = new FlareSolverr(
            $fsConfig['endpoint'],
            $fsConfig['max_timeout_ms'],
            $fsConfig['session_ttl_minutes'],
        );

        $parser = ParserRegistry::for($this->shop);
        $tally = [
            'added' => 0, 'updated' => 0, 'canonical' => 0,
            'non_product' => 0, 'failed' => 0,
        ];
        $delayMicroseconds = (int) ($this->config->downloadDelay() * 1_000_000);
        $first = true;

        try {
            foreach ($urls as $url) {
                if (! $first && $delayMicroseconds > 0) {
                    Sleep::usleep($delayMicroseconds);
                }
                $first = false;

                $this->progress->tick($tally);
                $this->claim($url);

                try {
                    $response = $flareSolverr->get($url);
                } catch (Throwable $e) {
                    $tally['failed']++;

                    $this->watchdog?->recordActivity();
                    fwrite(STDERR, sprintf("  fetch failed  %s  %s\n", $url, $e->getMessage()));
                    $this->markFailed($url, 'transport_error', null, $e->getMessage());

                    continue;
                }

                $this->watchdog?->recordActivity();

                if ($response['status'] !== 200) {
                    $tally['failed']++;
                    fwrite(STDERR, sprintf("  HTTP %d  %s\n", $response['status'], $url));
                    $this->markFailed($url, "http_{$response['status']}", $response['status']);

                    continue;
                }

                $this->markDone($url, $response['status'], strlen($response['body']));
                $parsed = $parser::parseProductPage($response['body']);

                $title = $parsed['title'] ?? null;
                if (! is_string($title) || trim($title) === '') {
                    $tally['failed']++;

                    continue;
                }

                if (($parsed['_emit_as'] ?? null) === 'book') {
                    try {
                        $this->canonical->upsert($parsed + ['source_url' => $url]);
                        $tally['canonical']++;
                    } catch (Throwable $e) {
                        $tally['failed']++;
                        fwrite(STDERR, sprintf("  persist failed  %s  %s\n", $url, $e->getMessage()));
                        $this->markFailed($url, 'persist_error', null, $e->getMessage());
                    }

                    continue;
                }

                if (($parsed['is_book_product'] ?? false) !== true) {
                    $tally['non_product']++;

                    continue;
                }

                try {
                    ['result' => $result] = $this->persister->persist(
                        $this->shopId,
                        $url,
                        $parsed,
                        $this->runId,
                    );
                    $result->created ? $tally['added']++ : $tally['updated']++;
                } catch (Throwable $e) {
                    $tally['failed']++;
                    fwrite(STDERR, sprintf("  persist failed  %s  %s\n", $url, $e->getMessage()));
                    $this->markFailed($url, 'persist_error', null, $e->getMessage());
                }
            }
        } finally {

            $flareSolverr->close();
        }

        return $tally;
    }

    private function claim(string $url): void
    {
        if ($this->runId !== null) {
            $this->queue->claim($this->runId, [$url]);
        }
    }

    private function markDone(string $url, int $httpStatus, int $responseBytes): void
    {
        if ($this->runId !== null) {
            $this->queue->markDone($this->runId, $url, $httpStatus, $responseBytes);
        }
    }

    private function markFailed(string $url, string $reason, ?int $httpStatus = null, ?string $detail = null): void
    {
        if ($this->runId !== null) {
            $this->queue->markFailed($this->runId, $url, $reason, $httpStatus, $detail);
        }
    }
}
