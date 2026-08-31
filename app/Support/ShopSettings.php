<?php

declare(strict_types=1);

namespace App\Support;

use App\Repositories\ShopSettingsRepository;
use Throwable;

final class ShopSettings
{
    private const DELAY_MIN = 0.1;

    private const DELAY_MAX = 60.0;

    private const CONCURRENCY_MIN = 1;

    private const CONCURRENCY_MAX = 16;

    /** @var array<string, array<string, array{value: string, type: string}>> */
    private static array $cache = [];

    public static function forgetCache(): void
    {
        self::$cache = [];
    }

    public static function downloadDelay(string $shop, float $fromToml): float
    {
        $value = self::float($shop, 'download_delay', $fromToml);

        return max(self::DELAY_MIN, min(self::DELAY_MAX, $value));
    }

    public static function concurrency(string $shop, int $fromToml): int
    {
        $value = (int) self::float($shop, 'concurrent_requests_per_domain', (float) $fromToml);

        return max(self::CONCURRENCY_MIN, min(self::CONCURRENCY_MAX, $value));
    }

    private static function float(string $shop, string $key, float $default): float
    {
        $row = self::rows($shop)[$key] ?? null;
        if ($row === null) {
            return $default;
        }
        if (! is_numeric($row['value'])) {
            fwrite(STDERR, sprintf(
                "  shop_settings.%s for %s is not numeric (%s) — using %s\n",
                $key,
                $shop,
                $row['value'],
                (string) $default
            ));

            return $default;
        }

        return (float) $row['value'];
    }

    /** @return array<string, array{value: string, type: string}> */
    private static function rows(string $shop): array
    {
        if (array_key_exists($shop, self::$cache)) {
            return self::$cache[$shop];
        }

        try {
            $resolved = (new ShopSettingsRepository)->forShop($shop);
        } catch (Throwable $e) {

            fwrite(STDERR, "  could not read shop_settings: {$e->getMessage()}\n");
            $resolved = [];
        }

        return self::$cache[$shop] = $resolved;
    }
}
