<?php

declare(strict_types=1);

namespace App\Crawler;

/**
 * Maps raw parser output onto the (data, properties) pair the repository
 * writes, mirroring the item construction in book_scraper/spiders/scan.py.
 */
final class ItemBuilder
{
    /**
     * Top-level parser keys that belong in shop_book_attributes rather than
     * on the shop_books row itself.
     */
    private const PROPERTY_KEYS = ['pages', 'cover_type', 'duration', 'narrator', 'translator'];

    /** Columns written directly onto shop_books. */
    private const DATA_KEYS = [
        'type', 'author', 'sku', 'isbn', 'publisher', 'year', 'format',
        'description', 'image_url', 'categories', 'price', 'price_original',
        'in_stock', 'planned_availability_date', 'rating', 'review_count',
    ];

    /**
     * @param  array<string, mixed>  $parsed  Output of Parser::parseProductPage.
     * @return array{data: array<string, mixed>, properties: array<string, mixed>|null}
     */
    public static function fromParsed(array $parsed): array
    {
        $data = [];
        foreach (self::DATA_KEYS as $key) {
            if (array_key_exists($key, $parsed)) {
                $data[$key] = $parsed[$key];
            }
        }
        $data['categories'] ??= [];

        // Parser-supplied properties first: shop-specific extras (humanitas's
        // `language`, pegasas's `ean`/`dimensions`) must survive into
        // shop_book_attributes. Without this merge anything outside the five
        // hardcoded keys below is silently dropped.
        $properties = [];
        if (isset($parsed['properties']) && is_array($parsed['properties'])) {
            $properties = $parsed['properties'];
        }
        foreach (self::PROPERTY_KEYS as $key) {
            if (($parsed[$key] ?? null) !== null && !array_key_exists($key, $properties)) {
                $properties[$key] = $parsed[$key];
            }
        }

        return ['data' => $data, 'properties' => $properties === [] ? null : $properties];
    }
}
