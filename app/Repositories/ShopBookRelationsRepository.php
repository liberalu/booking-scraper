<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ShopAuthor;
use App\Models\ShopBookAttribute;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

final class ShopBookRelationsRepository
{
    private const string MULTI_AUTHOR_PATTERN = '/(?:,\s|;|\s&\s|\s\/\s|\s+and\s+|\s+ir\s+)/iu';

    /** @param array<string, mixed> $properties */
    public function syncAttributes(int $shopBookId, array $properties): void
    {
        if ($properties === []) {
            return;
        }
        $existing = ShopBookAttribute::where('shop_book_id', $shopBookId)->get()->keyBy('key');
        foreach ($properties as $key => $value) {
            $stringValue = self::pythonString($value);
            $row = $existing->get($key);
            if ($row === null) {
                ShopBookAttribute::create([
                    'shop_book_id' => $shopBookId,
                    'key' => $key,
                    'value' => $stringValue,
                ]);
            } elseif ($row->value !== $stringValue) {
                $row->value = $stringValue;
                $row->save();
            }
        }
    }

    public function syncAuthors(int $shopBookId, ?string $authorRaw): void
    {
        $desired = [];
        $seen = [];
        $position = 0;
        foreach (self::splitAuthors($authorRaw) as $name) {
            $normalized = self::normalizeAuthor($name);
            if ($normalized === '') {
                continue;
            }
            $author = ShopAuthor::where('normalized_name', $normalized)->first();
            if ($author === null) {
                $author = ShopAuthor::create([
                    'name' => $name,
                    'normalized_name' => $normalized,
                    'created_at' => Carbon::now('UTC'),
                ]);
            }
            if (isset($seen[$author->id])) {
                continue;
            }
            $seen[$author->id] = true;
            $desired[$author->id] = $position++;
        }

        $existing = [];
        foreach (DB::table('shop_book_authors')->where('shop_book_id', $shopBookId)
            ->get(['author_id', 'position']) as $raw) {
            $row = DatabaseRow::from($raw);
            $existing[$row->int('author_id')] = $row->int('position');
        }
        foreach ($existing as $authorId => $currentPosition) {
            if (! array_key_exists($authorId, $desired)) {
                DB::table('shop_book_authors')->where('shop_book_id', $shopBookId)
                    ->where('author_id', $authorId)->delete();
            }
        }
        foreach ($desired as $authorId => $wanted) {
            if (! array_key_exists($authorId, $existing)) {
                DB::table('shop_book_authors')->insert([
                    'shop_book_id' => $shopBookId,
                    'author_id' => $authorId,
                    'position' => $wanted,
                ]);
            } elseif ($existing[$authorId] !== $wanted) {
                DB::table('shop_book_authors')->where('shop_book_id', $shopBookId)
                    ->where('author_id', $authorId)->update(['position' => $wanted]);
            }
        }
    }

    /** @return list<string> */
    public static function splitAuthors(?string $raw): array
    {
        if ($raw === null || trim($raw) === '') {
            return [];
        }
        $split = preg_split(self::MULTI_AUTHOR_PATTERN, $raw);
        $parts = array_values(array_filter(
            array_map(static fn (string $part): string => trim($part), $split === false ? [] : $split),
            static fn (string $part): bool => $part !== '',
        ));

        return $parts !== [] ? $parts : [trim($raw)];
    }

    public static function normalizeAuthor(string $name): string
    {
        return trim(preg_replace('/\s+/u', ' ', mb_strtolower(trim($name), 'UTF-8')) ?? '');
    }

    private static function pythonString(mixed $value): ?string
    {
        if ($value === null) {
            return null;
        }
        if (is_bool($value)) {
            return $value ? 'True' : 'False';
        }
        if (is_float($value)) {
            if (is_nan($value)) {
                return 'nan';
            }
            if (is_infinite($value)) {
                return $value > 0 ? 'inf' : '-inf';
            }
            $text = json_encode($value, JSON_THROW_ON_ERROR);

            return preg_match('/[.eE]/', $text) === 1 ? $text : $text.'.0';
        }
        if (is_array($value)) {
            return json_encode($value, JSON_THROW_ON_ERROR);
        }

        return is_int($value) || is_string($value) ? (string) $value : null;
    }
}
