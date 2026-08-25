<?php

declare(strict_types=1);

namespace BookScraper\Crawler;

use BookScraper\Config;
use BookScraper\ParserRegistry;
use BookScraper\Repository\CanonicalBookRepository;
use Throwable;

/**
 * Scans a FlareSolverr-backed shop one URL at a time.
 *
 * Deliberately not routed through roach. FlareSolverr reuses a single
 * browser session so the Cloudflare clearance cookie sticks, and two
 * concurrent `request.get` calls on that session race for the same browser
 * — the second response silently returns the FIRST request's body. That is
 * the 2026-05-22 humanitas regression, where one product's metadata was
 * written to another product's row.
 *
 * Serial execution makes that impossible by construction rather than by
 * remembering to set concurrency=1. roach's concurrency machinery would add
 * nothing here anyway, since the ceiling is 1.
 */
final class SerialScanner
{
    public function __construct(
        private readonly string $shop,
        private readonly Config $config,
        private readonly Persister $persister,
        private readonly int $shopId,
        private readonly ?int $runId,
        private readonly ?Watchdog $watchdog = null,
        private readonly CanonicalBookRepository $canonical = new CanonicalBookRepository(),
    ) {}

    /**
     * @param  list<string>  $urls
     * @return array<string, int>  tally: added / updated / canonical /
     *                             non_product / failed
     */
    public function run(array $urls): array
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

        try {
            foreach ($urls as $index => $url) {
                if ($index > 0 && $delayMicroseconds > 0) {
                    usleep($delayMicroseconds);
                }

                try {
                    $response = $flareSolverr->get($url);
                } catch (Throwable $e) {
                    $tally['failed']++;
                    fwrite(STDERR, sprintf("  fetch failed  %s  %s\n", $url, $e->getMessage()));
                    continue;
                }

                // Every fetch counts as progress, including a failed one —
                // the watchdog is asking "is this process alive", not "is it
                // succeeding".
                $this->watchdog?->recordActivity();

                if ($response['status'] !== 200) {
                    $tally['failed']++;
                    fwrite(STDERR, sprintf("  HTTP %d  %s\n", $response['status'], $url));
                    continue;
                }

                $parsed = $parser::parseProductPage($response['body']);

                $title = $parsed['title'] ?? null;
                if (!is_string($title) || trim($title) === '') {
                    $tally['failed']++;
                    continue;
                }

                // Same branches as ScanSpider, in the same order. A
                // bibliographic record goes to the canonical `books` table;
                // no FlareSolverr shop emits those today, but the two paths
                // diverging silently is exactly how the tag got ignored in
                // the first place.
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

                // A non-book is a successful scrape whose outcome is "not a
                // product", so nothing is written to shop_books.
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
            // Always tear the session down: an orphaned FlareSolverr session
            // keeps a Chromium instance alive in the sidecar.
            $flareSolverr->close();
        }

        return $tally;
    }
}
