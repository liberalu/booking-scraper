<?php

declare(strict_types=1);

namespace App\Support;

use PhpCollective\Toml\Toml;
use RuntimeException;

final class Config
{
    /** @var array<string, int|float> */
    private array $overrides = [];

    private const FALLBACKS = [
        'download_delay' => 1.0,
        'concurrent_requests_per_domain' => 1,
        'max_retries' => 2,
        'connect_timeout' => 5,
        'read_timeout' => 10,
        'hard_timeout' => 30,
    ];

    /**
     * @param  array<string, mixed>  $shop
     * @param  array<string, mixed>  $default
     */
    private function __construct(
        public readonly string $name,
        private readonly array $shop,
        private readonly array $default,
    ) {}

    public static function forShop(string $shop, ?string $configDir = null): self
    {
        $dir = $configDir ?? dirname(__DIR__, 2).'/config';
        $shopPath = "{$dir}/shops/{$shop}.toml";
        if (! is_file($shopPath)) {
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
        $url = self::map($this->shop['shop'] ?? null)['base_url'] ?? null;
        if (! is_string($url) || $url === '') {
            throw new RuntimeException("[shop].base_url missing for {$this->name}");
        }

        return $url;
    }

    public function downloadDelay(): float
    {
        return $this->floatSetting('download_delay');
    }

    public function concurrency(): int
    {
        return $this->intSetting('concurrent_requests_per_domain');
    }

    public function maxRetries(): int
    {
        return $this->intSetting('max_retries');
    }

    public function requestTimeout(): float
    {
        return $this->floatSetting('hard_timeout');
    }

    public function connectTimeout(): float
    {
        return $this->floatSetting('connect_timeout');
    }

    public function matchTrust(int $default = 50): int
    {
        $trust = self::map($this->shop['match'] ?? null)['trust'] ?? null;

        return is_numeric($trust) ? (int) $trust : $default;
    }

    /** @return array{endpoint: string, max_timeout_ms: int, session_ttl_minutes: int}|null */
    public function flaresolverr(): ?array
    {
        $block = self::map($this->shop['flaresolverr'] ?? null);
        $configuredEndpoint = $block['endpoint'] ?? null;
        if (! is_string($configuredEndpoint) || $configuredEndpoint === '') {
            return null;
        }

        $environmentEndpoint = getenv('FLARESOLVERR_ENDPOINT');
        $endpoint = is_string($environmentEndpoint) && $environmentEndpoint !== ''
            ? $environmentEndpoint
            : $configuredEndpoint;

        return [
            'endpoint' => $endpoint,
            'max_timeout_ms' => self::integer($block['max_timeout_ms'] ?? null, 120000),
            'session_ttl_minutes' => self::integer($block['session_ttl_minutes'] ?? null, 25),
        ];
    }

    /** @return array<string, mixed> */
    public function strategy(string $name): array
    {
        $strategy = self::map($this->shop['discover'] ?? null)[$name] ?? null;
        if (! is_array($strategy)) {
            throw new RuntimeException(
                "No [discover.{$name}] block in config/shops/{$this->name}.toml"
            );
        }

        return self::map($strategy);
    }

    /** @return non-empty-list<string> */
    public function strategyUrls(string $name): array
    {
        $url = $this->strategy($name)['url'] ?? null;
        if (is_string($url) && $url !== '') {
            return [$url];
        }
        if (is_array($url)) {
            $urls = array_values(array_filter($url, static fn (mixed $value): bool => is_string($value) && $value !== ''));
            if ($urls !== []) {
                return $urls;
            }
        }

        throw new RuntimeException("[discover.{$name}] has no url");
    }

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

    public function urlIncludePattern(): ?string
    {
        $pattern = self::map($this->shop['discover'] ?? null)['url_include_pattern'] ?? null;

        return is_string($pattern) && $pattern !== '' ? $pattern : null;
    }

    /**
     * @return array{allowed_keys: list<string>, rules: array<string, array<string, mixed>>}|null
     */
    public function attributes(): ?array
    {
        $rawBlock = $this->shop['attributes'] ?? null;
        if (! is_array($rawBlock)) {
            return null;
        }
        $block = self::map($rawBlock);
        $rules = [];
        foreach ($block as $key => $value) {
            if ($key !== 'allowed_keys' && is_array($value)) {
                $rules[$key] = self::map($value);
            }
        }

        $allowedKeys = [];
        $rawAllowedKeys = $block['allowed_keys'] ?? null;
        if (is_array($rawAllowedKeys)) {
            foreach ($rawAllowedKeys as $allowedKey) {
                if (is_string($allowedKey)) {
                    $allowedKeys[] = $allowedKey;
                }
            }
        }

        return [
            'allowed_keys' => $allowedKeys,
            'rules' => $rules,
        ];
    }

    public function hasStrategy(string $name): bool
    {
        return is_array(self::map($this->shop['discover'] ?? null)[$name] ?? null);
    }

    private function setting(string $key): mixed
    {

        return $this->overrides[$key]
            ?? self::map($this->shop['scraping'] ?? null)[$key]
            ?? self::map($this->default['scrapy'] ?? null)[$key]
            ?? self::FALLBACKS[$key]
            ?? throw new RuntimeException("No value or fallback for setting '{$key}'");
    }

    private function floatSetting(string $key): float
    {
        $value = $this->setting($key);
        if (! is_int($value) && ! is_float($value) && ! (is_string($value) && is_numeric($value))) {
            throw new RuntimeException("Setting '{$key}' must be numeric.");
        }

        return (float) $value;
    }

    private function intSetting(string $key): int
    {
        $value = $this->setting($key);
        if (! is_int($value) && ! (is_string($value) && is_numeric($value))) {
            throw new RuntimeException("Setting '{$key}' must be an integer.");
        }

        return (int) $value;
    }

    private static function integer(mixed $value, int $default): int
    {
        if (is_int($value)) {
            return $value;
        }
        if (is_string($value) && is_numeric($value)) {
            return (int) $value;
        }

        return $default;
    }

    /** @return array<string, mixed> */
    private static function map(mixed $value): array
    {
        if (! is_array($value)) {
            return [];
        }

        $map = [];
        foreach ($value as $key => $item) {
            if (is_string($key)) {
                $map[$key] = $item;
            }
        }

        return $map;
    }
}
