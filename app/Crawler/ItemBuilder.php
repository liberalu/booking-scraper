<?php

declare(strict_types=1);

namespace App\Crawler;

/**
 * @phpstan-import-type ParsedItem from CrawlerTypes
 * @phpstan-import-type ItemPayload from CrawlerTypes
 */
final class ItemBuilder
{
    private const array PROPERTY_KEYS = ['pages', 'cover_type', 'duration', 'narrator', 'translator'];

    private const array DATA_KEYS = [
        'type', 'author', 'sku', 'isbn', 'publisher', 'year', 'format',
        'description', 'image_url', 'categories', 'price', 'price_original',
        'in_stock', 'planned_availability_date', 'rating', 'review_count',
    ];

    /**
     * @param  ParsedItem  $parsed
     * @return ItemPayload
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

        $properties = [];
        $rawProperties = $parsed['properties'] ?? null;
        if (is_array($rawProperties)) {
            foreach ($rawProperties as $key => $value) {
                if (is_string($key)) {
                    $properties[$key] = $value;
                }
            }
        }
        foreach (self::PROPERTY_KEYS as $key) {
            if (($parsed[$key] ?? null) !== null && ! array_key_exists($key, $properties)) {
                $properties[$key] = $parsed[$key];
            }
        }

        return ['data' => $data, 'properties' => $properties === [] ? null : $properties];
    }
}
