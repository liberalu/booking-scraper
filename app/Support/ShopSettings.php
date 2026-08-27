<?php

declare(strict_types=1);

namespace App\Support;

use Illuminate\Support\Facades\DB;
use Throwable;

/**
 * Operator overrides from the `shop_settings` table.
 *
 * The top tier of the rate-limit precedence chain: a DB row beats the shop's
 * TOML, which beats the built-in fallback. It exists so a shop that starts
 * rate-limiting mid-crawl can be slowed down with one INSERT, without a
 * redeploy — which is the whole point, and why reading only the TOML (as this
 * port did) quietly removed the incident lever.
 *
 * Resolved per key, not per block: a row for `download_delay` does not stop
 * `concurrent_requests_per_domain` falling through to the TOML.
 */
final class ShopSettings
{
    /** Same clamps the Python handler applies, so a bad row cannot stall or flood. */
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

    /** The effective delay for a shop, in seconds. */
    public static function downloadDelay(string $shop, float $fromToml): float
    {
        $value = self::float($shop, 'download_delay', $fromToml);

        return max(self::DELAY_MIN, min(self::DELAY_MAX, $value));
    }

    /** The effective in-flight request cap for a shop. */
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
        if (!is_numeric($row['value'])) {
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

    /**
     * @return array<string, array{value: string, type: string}>
     */
    private static function rows(string $shop): array
    {
        if (array_key_exists($shop, self::$cache)) {
            return self::$cache[$shop];
        }

        try {
            $rows = DB::table('shop_settings')
                ->join('shops', 'shops.id', '=', 'shop_settings.shop_id')
                ->where('shops.name', $shop)
                ->get(['shop_settings.key', 'shop_settings.value', 'shop_settings.type']);
            $resolved = [];
            foreach ($rows as $row) {
                $resolved[(string) $row->key] = [
                    'value' => (string) $row->value,
                    'type' => (string) $row->type,
                ];
            }
        } catch (Throwable $e) {
            // An unreadable override table must not stop a crawl: fall through
            // to the TOML, which is what the operator had before.
            fwrite(STDERR, "  could not read shop_settings: {$e->getMessage()}\n");
            $resolved = [];
        }

        return self::$cache[$shop] = $resolved;
    }
}
