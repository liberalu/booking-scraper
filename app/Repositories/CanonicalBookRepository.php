<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Support\Isbn;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;

final class CanonicalBookRepository
{
    private const array FIELDS = [
        'title', 'title_full', 'year', 'release_place', 'type', 'format',
        'pages', 'duration', 'dimensions', 'language', 'translated_from',
        'description', 'cover_url', 'upcoming_release', 'udc_codes',
        'subjects', 'audience', 'libis_rating', 'libis_review_count',
        'source_url',
    ];

    private const array ARRAY_FIELDS = ['translated_from', 'udc_codes', 'subjects'];

    /** @param array<string, mixed> $item */
    public function upsert(array $item): int
    {
        return DB::transaction(function () use ($item): int {
            $isbns = $this->normalisedIsbns($item['isbns'] ?? []);
            $libisCode = $this->text($item['libis_code'] ?? null);

            $bookId = null;
            if ($isbns !== []) {
                $found = DB::table('books')
                    ->join('book_isbns', 'book_isbns.book_id', '=', 'books.id')
                    ->whereIn('book_isbns.isbn', array_keys($isbns))
                    ->value('books.id');
                $bookId = $this->id($found);
            }
            if ($bookId === null && $libisCode !== null) {
                $found = DB::table('books')->where('libis_code', $libisCode)->value('id');
                $bookId = $this->id($found);
            }

            $publisherId = $this->findOrCreate('publishers', 'name', $this->text($item['publisher'] ?? null));
            $seriesId = $this->findOrCreate('series', 'title', $this->text($item['series'] ?? null));

            $fields = [];
            foreach (self::FIELDS as $field) {
                $value = $item[$field] ?? null;
                if ($value === null) {
                    continue;
                }
                $fields[$field] = in_array($field, self::ARRAY_FIELDS, true)
                    ? $this->pgArray($value)
                    : $value;
            }
            if ($seriesId !== null) {
                $fields['series_id'] = $seriesId;
            }

            if ($bookId === null) {
                $bookId = DB::table('books')->insertGetId($fields + [
                    'data_source' => $item['data_source'] ?? 'ibiblioteka',
                    'libis_code' => $libisCode,
                    'publisher_id' => $publisherId,
                    'upcoming_release' => $fields['upcoming_release'] ?? false,
                    'created_at' => Date::now('UTC'),
                    'updated_at' => Date::now('UTC'),
                ], 'id');
            } else {
                $current = DB::table('books')->where('id', $bookId)->first();

                $currentRow = DatabaseRow::nullable($current);
                if ($currentRow?->nullableString('data_source') === 'shop_inferred'
                    && ($item['data_source'] ?? null) === 'ibiblioteka') {
                    $fields['data_source'] = 'ibiblioteka';
                    $fields['libis_code'] = $libisCode;
                }
                if ($currentRow?->nullableInt('publisher_id') === null && $publisherId !== null) {
                    $fields['publisher_id'] = $publisherId;
                }
                if ($libisCode !== null && $currentRow?->nullableString('libis_code') === null) {
                    $fields['libis_code'] = $libisCode;
                }

                DB::table('books')->where('id', $bookId)->update($fields);
            }

            foreach ($isbns as $isbn) {
                $this->upsertIsbn($bookId, $isbn['isbn'], $isbn['type']);
            }
            $authors = $item['authors'] ?? null;
            foreach (is_array($authors) ? $authors : [] as $author) {
                if (is_array($author)) {
                    $this->upsertAuthor($bookId, $this->map($author));
                }
            }

            return $bookId;
        });
    }

    /** @return list<array{isbn: string, type: string}> */
    private function normalisedIsbns(mixed $entries): array
    {
        if (! is_array($entries)) {
            return [];
        }
        $out = [];
        $seen = [];
        foreach ($entries as $entry) {
            $raw = is_array($entry) ? ($entry['isbn'] ?? null) : $entry;

            $normalised = is_string($raw) ? Isbn::normalize($raw) : '';
            if ($normalised === '' || isset($seen[$normalised])) {
                continue;
            }
            $type = is_array($entry) ? $entry['type'] ?? null : null;
            $out[] = [
                'isbn' => $normalised,
                'type' => is_string($type) && $type !== '' ? $type : 'unknown',
            ];
            $seen[$normalised] = true;

            $opposite = strlen($normalised) === 13
                ? Isbn::toIsbn10($normalised)
                : Isbn::toIsbn13($normalised);
            if ($opposite !== null && $opposite !== $normalised && ! isset($seen[$opposite])) {
                $out[] = [
                    'isbn' => $opposite,
                    'type' => strlen($opposite) === 10 ? 'isbn10' : 'isbn13',
                ];
                $seen[$opposite] = true;
            }
        }

        return $out;
    }

    private function upsertIsbn(int $bookId, string $isbn, string $type): void
    {
        DB::statement(
            'insert into book_isbns (book_id, isbn, isbn_type) values (?, ?, ?)'
            .' on conflict (isbn) do update set book_id = excluded.book_id,'
            .' isbn_type = excluded.isbn_type',
            [$bookId, $isbn, $type]
        );
    }

    /** @param array<string, mixed> $entry */
    private function upsertAuthor(int $bookId, array $entry): void
    {
        $name = $this->text($entry['name'] ?? null) ?? '';
        if ($name === '') {
            return;
        }
        $libisCode = $this->text($entry['libis_code'] ?? null);

        $normalised = trim(str_replace(',', '', mb_strtolower($name)));

        $authorId = null;
        if ($libisCode !== null) {
            $found = DB::table('authors')->where('libis_code', $libisCode)->value('id');
            $authorId = $this->id($found);
        }
        if ($authorId === null) {
            $found = DB::table('authors')->where('normalized_name', $normalised)->value('id');
            $authorId = $this->id($found);
        }
        if ($authorId === null) {
            $authorId = DB::table('authors')->insertGetId([
                'name' => $name,
                'normalized_name' => $normalised,
                'libis_code' => $libisCode,
            ], 'id');
        } elseif ($libisCode !== null) {
            DB::table('authors')
                ->where('id', $authorId)
                ->whereNull('libis_code')
                ->update(['libis_code' => $libisCode]);
        }

        $role = $this->text($entry['role'] ?? null) ?? 'author';
        $position = DatabaseRow::from(['position' => $entry['position'] ?? 0])->int('position');
        $existing = DB::table('book_authors')
            ->where(['book_id' => $bookId, 'author_id' => $authorId, 'role' => $role])
            ->exists();
        if ($existing) {
            DB::table('book_authors')
                ->where(['book_id' => $bookId, 'author_id' => $authorId, 'role' => $role])
                ->update(['position' => $position]);
        } else {
            DB::table('book_authors')->insert([
                'book_id' => $bookId,
                'author_id' => $authorId,
                'role' => $role,
                'position' => $position,
            ]);
        }
    }

    private function findOrCreate(string $table, string $column, ?string $value): ?int
    {
        if ($value === null) {
            return null;
        }
        $existing = DB::table($table)->where($column, $value)->value('id');
        if ($existing !== null) {
            return $this->id($existing);
        }

        return DB::table($table)->insertGetId([$column => $value], 'id');
    }

    private function text(mixed $value): ?string
    {
        if (! is_string($value)) {
            return null;
        }

        return trim($value) === '' ? null : trim($value);
    }

    private function pgArray(mixed $value): ?string
    {
        if (! is_array($value)) {
            return null;
        }
        $parts = [];
        foreach ($value as $element) {
            if ($element === null) {
                $parts[] = 'NULL';

                continue;
            }
            $text = $this->text($element);
            if ($text !== null) {
                $parts[] = '"'.str_replace(['\\', '"'], ['\\\\', '\\"'], $text).'"';
            }
        }

        return '{'.implode(',', $parts).'}';
    }

    private function id(mixed $value): ?int
    {
        return DatabaseRow::from(['id' => $value])->nullableInt('id');
    }

    /**
     * @param  array<mixed>  $value
     * @return array<string, mixed>
     */
    private function map(array $value): array
    {
        $map = [];
        foreach ($value as $key => $item) {
            if (is_string($key)) {
                $map[$key] = $item;
            }
        }

        return $map;
    }
}
