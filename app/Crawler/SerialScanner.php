<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Repositories\CanonicalBookRepository;
use App\Runs\ProgressReporter;
use App\Support\Config;
use App\Support\ParserRegistry;
use Throwable;

final class SerialScanner
{
    public function __construct(
        private readonly string $shop,
        private readonly Config $config,
        private readonly Persister $persister,
        private readonly int $shopId,
        private readonly ?int $runId,
        private readonly ?Watchdog $watchdog = null,
        private readonly CanonicalBookRepository $canonical = new CanonicalBookRepository,
        private readonly ProgressReporter $progress = new ProgressReporter,
    ) {}

    /**
     * @param  iterable<string>  $urls
     * @return array{added: int, updated: int, canonical: int, non_product: int, failed: int}
     */
    public function run(iterable $urls): array
    {
        $fsConfig = $this->config->flaresolverr();
        if ($fsConfig === null) {
            throw new \RuntimeException("shop {$this->shop} has no [flaresolverr] block");
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
                    usleep($delayMicroseconds);
                }
                $first = false;

                $this->progress->tick($tally);

                try {
                    $response = $flareSolverr->get($url);
                } catch (Throwable $e) {
                    $tally['failed']++;

                    $this->watchdog?->recordActivity();
                    fwrite(STDERR, sprintf("  fetch failed  %s  %s\n", $url, $e->getMessage()));

                    continue;
                }

                $this->watchdog?->recordActivity();

                if ($response['status'] !== 200) {
                    $tally['failed']++;
                    fwrite(STDERR, sprintf("  HTTP %d  %s\n", $response['status'], $url));

                    continue;
                }

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
                }
            }
        } finally {

            $flareSolverr->close();
        }

        return $tally;
    }
}
