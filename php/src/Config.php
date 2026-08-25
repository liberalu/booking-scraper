<?php

declare(strict_types=1);

namespace BookScraper;

use RuntimeException;
use PhpCollective\Toml\Toml;

/**
 * Reads the SAME TOML files as the Python stack (config/default.toml and
 * config/shops/<shop>.toml). Deliberately not a PHP-side copy of the
 * config: during the port both stacks run against one catalogue, and two
 * drifting copies of `download_delay` is a rate-limit incident waiting to
 * happen.
 *
 * Precedence mirrors HttpxMiddleware.spider_opened, minus the DB tier:
 *   shop [scraping] -> default [scrapy] -> hardcoded fallback.
 * The `shop_settings` DB tier is applied by ShopSettings at runtime.
 */
final class Config
{
    /**
     * Values from `shop_settings`, empty until applyShopSettings() runs.
     *
     * @var array<string, float|int>
     */
    private array $overrides = [];

    private const FALLBACKS = [
        'download_delay' => 1.0,
        'concurrent_requests_per_domain' => 1,
        'max_retries' => 2,
        'connect_timeout' => 5,
        'read_timeout' => 10,
        'hard_timeout' => 30,
    ];

    /** @param array<string, mixed> $shop */
    private function __construct(
        public readonly string $name,
        private readonly array $shop,
        private readonly array $default,
    ) {}

    public static function forShop(string $shop, ?string $configDir = null): self
    {
        $dir = $configDir ?? dirname(__DIR__, 2) . '/config';
        $shopPath = "{$dir}/shops/{$shop}.toml";
        if (!is_file($shopPath)) {
            throw new RuntimeException("Shop config not found: {$shopPath}");
        }

        $defaultPath = "{$dir}/default.toml";

        return new self(
            $shop,
            Toml::decodeFile($shopPath),
            is_file($defaultPath) ? Toml::decodeFile($defaultPath) : [],
        );
    }

    public function baseUrl(): string
    {
        $url = $this->shop['shop']['base_url'] ?? null;
        if (!is_string($url) || $url === '') {
            throw new RuntimeException("[shop].base_url missing for {$this->name}");
        }

        return $url;
    }

    public function downloadDelay(): float
    {
        return (float) $this->setting('download_delay');
    }

    public function concurrency(): int
    {
        return (int) $this->setting('concurrent_requests_per_domain');
    }

    public function maxRetries(): int
    {
        return (int) $this->setting('max_retries');
    }

    /** Per-request timeout budget, in seconds, for the Guzzle client. */
    public function requestTimeout(): float
    {
        return (float) $this->setting('hard_timeout');
    }

    public function connectTimeout(): float
    {
        return (float) $this->setting('connect_timeout');
    }

    /**
     * `[match] trust` — how much this shop's metadata is believed when
     * synthesising a canonical record from several shops' data.
     */
    public function matchTrust(int $default = 50): int
    {
        $trust = $this->shop['match']['trust'] ?? null;

        return is_numeric($trust) ? (int) $trust : $default;
    }

    /**
     * The `[flaresolverr]` block, or null when the shop doesn't need it.
     *
     * Presence of the block is what opts a shop in — humanitas has a
     * Cloudflare Managed Challenge on every URL, so plain requests there
     * return a challenge page rather than content.
     *
     * @return array{endpoint: string, max_timeout_ms: int, session_ttl_minutes: int}|null
     */
    public function flaresolverr(): ?array
    {
        $block = $this->shop['flaresolverr'] ?? null;
        if (!is_array($block) || ($block['endpoint'] ?? '') === '') {
            return null;
        }

        // The compose hostname only resolves inside the network; a CLI run on
        // the host needs localhost. FLARESOLVERR_ENDPOINT overrides both.
        $endpoint = (string) (getenv('FLARESOLVERR_ENDPOINT') ?: $block['endpoint']);

        return [
            'endpoint' => $endpoint,
            'max_timeout_ms' => (int) ($block['max_timeout_ms'] ?? 120000),
            'session_ttl_minutes' => (int) ($block['session_ttl_minutes'] ?? 25),
        ];
    }

    /** A [discover.<strategy>] subtable, e.g. `sitemap` or `categories`. */
    public function strategy(string $name): array
    {
        $strategy = $this->shop['discover'][$name] ?? null;
        if (!is_array($strategy)) {
            throw new RuntimeException(
                "No [discover.{$name}] block in config/shops/{$this->name}.toml"
            );
        }

        return $strategy;
    }

    /**
     * Layer the `shop_settings` DB rows on top of the TOML.
     *
     * Called once, after the database is up, so every later
     * `downloadDelay()` / `concurrency()` reader sees the effective value —
     * including the ones inside SerialScanner and the roach container. Doing
     * it here rather than at each call site is what keeps a new reader from
     * silently bypassing the operator override.
     */
    public function applyShopSettings(string $shop): void
    {
        $this->overrides = [
            'download_delay' => ShopSettings::downloadDelay($shop, $this->downloadDelay()),
            'concurrent_requests_per_domain' => ShopSettings::concurrency(
                $shop,
                $this->concurrency()
            ),
        ];
    }

    /**
     * The regex a discovered URL must match to count as a product, or null.
     *
     * Shops list far more than products in a sitemap — author pages, blog
     * posts, category listings. Without the filter those all become
     * `discovered_urls` rows the scan phase then fetches and discards.
     */
    public function urlIncludePattern(): ?string
    {
        $pattern = $this->shop['discover']['url_include_pattern'] ?? null;

        return is_string($pattern) && $pattern !== '' ? $pattern : null;
    }

    /**
     * The per-shop attribute schema, or null when the shop declares none.
     *
     * Opt-in: with no `[attributes]` block every scraped attribute passes
     * unchecked, which is the case for every shop today. TOML subtables
     * (`[attributes.format]`) arrive as sibling keys, so anything that is
     * itself a table becomes a rule.
     *
     * @return array{allowed_keys: list<string>, rules: array<string, array<string, mixed>>}|null
     */
    public function attributes(): ?array
    {
        $block = $this->shop['attributes'] ?? null;
        if (!is_array($block)) {
            return null;
        }
        $rules = [];
        foreach ($block as $key => $value) {
            if ($key !== 'allowed_keys' && is_array($value)) {
                $rules[(string) $key] = $value;
            }
        }

        return [
            'allowed_keys' => array_map('strval', (array) ($block['allowed_keys'] ?? [])),
            'rules' => $rules,
        ];
    }

    public function hasStrategy(string $name): bool
    {
        return is_array($this->shop['discover'][$name] ?? null);
    }

    private function setting(string $key): mixed
    {
        // An operator override, when one has been applied, outranks every
        // file-based tier.
        return $this->overrides[$key]
            ?? $this->shop['scraping'][$key]
            ?? $this->default['scrapy'][$key]
            ?? self::FALLBACKS[$key]
            ?? throw new RuntimeException("No value or fallback for setting '{$key}'");
    }
}
