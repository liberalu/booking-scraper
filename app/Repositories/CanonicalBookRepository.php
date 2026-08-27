<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Support\Isbn;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * Upserts a canonical `books` row from a library record.
 *
 * This is the ibiblioteka path: its scan yields a BookItem, not a
 * ShopBookItem, because the national library is a bibliographic source, not a
 * shop — there is no price, no stock, no URL to buy. Persisting one of those
 * as a `shop_books` row (which is what happens if the `_emit_as` tag is
 * ignored) produces a shop with 80k books and no prices.
 *
 * Mirrors PostgresPipeline._upsert_book.
 */
final class CanonicalBookRepository
{
    /**
     * Fields copied onto the row when present. A null is "not supplied" and
     * leaves the existing value alone — a partial re-scrape must not blank
     * out data an earlier, richer one captured.
     */
    private const FIELDS = [
        'title', 'title_full', 'year', 'release_place', 'type', 'format',
        'pages', 'duration', 'dimensions', 'language', 'translated_from',
        'description', 'cover_url', 'upcoming_release', 'udc_codes',
        'subjects', 'audience', 'libis_rating', 'libis_review_count',
        'source_url',
    ];

    /** Postgres text[] columns — passed as literals, not PHP arrays. */
    private const ARRAY_FIELDS = ['translated_from', 'udc_codes', 'subjects'];

    /**
     * @param  array<string, mixed>  $item  A BookItem-shaped parser result.
     * @return int the canonical book id
     */
    public function upsert(array $item): int
    {
        return DB::transaction(function () use ($item): int {
            $isbns = $this->normalisedIsbns($item['isbns'] ?? []);
            $libisCode = $this->text($item['libis_code'] ?? null);

            // Match by ISBN first, then by libis_code — a re-scrape can carry
            // different ISBNs for the same record, and the library code is
            // the stable identity in that case.
            $bookId = null;
            if ($isbns !== []) {
                $found = DB::table('books')
                    ->join('book_isbns', 'book_isbns.book_id', '=', 'books.id')
                    ->whereIn('book_isbns.isbn', array_keys($isbns))
                    ->value('books.id');
                $bookId = $found === null ? null : (int) $found;
            }
            if ($bookId === null && $libisCode !== null) {
                $found = DB::table('books')->where('libis_code', $libisCode)->value('id');
                $bookId = $found === null ? null : (int) $found;
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
                $bookId = (int) DB::table('books')->insertGetId($fields + [
                    'data_source' => $item['data_source'] ?? 'ibiblioteka',
                    'libis_code' => $libisCode,
                    'publisher_id' => $publisherId,
                    'upcoming_release' => $fields['upcoming_release'] ?? false,
                    'created_at' => Carbon::now('UTC'),
                    'updated_at' => Carbon::now('UTC'),
                ], 'id');
            } else {
                $current = DB::table('books')->where('id', $bookId)->first();
                // A book synthesised from shop data is upgraded when the real
                // library record arrives: the library is the better source.
                if (($current->data_source ?? null) === 'shop_inferred'
                    && ($item['data_source'] ?? null) === 'ibiblioteka') {
                    $fields['data_source'] = 'ibiblioteka';
                    $fields['libis_code'] = $libisCode;
                }
                if (($current->publisher_id ?? null) === null && $publisherId !== null) {
                    $fields['publisher_id'] = $publisherId;
                }
                if ($libisCode !== null && ($current->libis_code ?? null) === null) {
                    $fields['libis_code'] = $libisCode;
                }
                // `updated_at` is deliberately NOT bumped: the Python model
                // declares it server_default-only with no onupdate, so it
                // stays at creation time there. Bumping it here would make
                // every re-scrape look like a divergence.
                DB::table('books')->where('id', $bookId)->update($fields);
            }

            foreach ($isbns as $isbn => $type) {
                $this->upsertIsbn($bookId, (string) $isbn, $type);
            }
            foreach ($item['authors'] ?? [] as $author) {
                if (is_array($author)) {
                    $this->upsertAuthor($bookId, $author);
                }
            }

            return $bookId;
        });
    }

    /**
     * ISBNs keyed by normalised value, each with its type — plus the opposite
     * form of every one, so a lookup by ISBN-10 finds a book catalogued
     * under its ISBN-13 and vice versa.
     *
     * @param  mixed  $entries
     * @return array<string, string>
     */
    private function normalisedIsbns(mixed $entries): array
    {
        if (!is_array($entries)) {
            return [];
        }
        $out = [];
        foreach ($entries as $entry) {
            $raw = is_array($entry) ? ($entry['isbn'] ?? null) : $entry;
            // Strip only — Python's normalize_isbn does no validation, so an
            // invalid-looking code from the library still gets catalogued
            // rather than silently dropped.
            $normalised = is_string($raw) ? Isbn::normalize($raw) : '';
            if ($normalised === '' || isset($out[$normalised])) {
                continue;
            }
            $type = is_array($entry) ? $entry['type'] ?? null : null;
            $out[$normalised] = is_string($type) && $type !== '' ? $type : 'unknown';

            $opposite = strlen($normalised) === 13
                ? Isbn::toIsbn10($normalised)
                : Isbn::toIsbn13($normalised);
            if ($opposite !== null && $opposite !== $normalised && !isset($out[$opposite])) {
                $out[$opposite] = strlen($opposite) === 10 ? 'isbn10' : 'isbn13';
            }
        }

        return $out;
    }

    /**
     * `book_isbns.isbn` is globally unique, so a conflict means the ISBN is
     * currently attributed to another book — the newer record wins, which is
     * what the Python upsert does.
     */
    private function upsertIsbn(int $bookId, string $isbn, string $type): void
    {
        DB::statement(
            'insert into book_isbns (book_id, isbn, isbn_type) values (?, ?, ?)'
            . ' on conflict (isbn) do update set book_id = excluded.book_id,'
            . ' isbn_type = excluded.isbn_type',
            [$bookId, $isbn, $type]
        );
    }

    /** @param array<string, mixed> $entry */
    private function upsertAuthor(int $bookId, array $entry): void
    {
        $name = trim((string) ($entry['name'] ?? ''));
        if ($name === '') {
            return;
        }
        $libisCode = $this->text($entry['libis_code'] ?? null);
        // Note: this normalisation drops commas but not extra whitespace —
        // matching Python, so both stacks dedup authors identically.
        $normalised = trim(str_replace(',', '', mb_strtolower($name)));

        $authorId = null;
        if ($libisCode !== null) {
            $found = DB::table('authors')->where('libis_code', $libisCode)->value('id');
            $authorId = $found === null ? null : (int) $found;
        }
        if ($authorId === null) {
            $found = DB::table('authors')->where('normalized_name', $normalised)->value('id');
            $authorId = $found === null ? null : (int) $found;
        }
        if ($authorId === null) {
            $authorId = (int) DB::table('authors')->insertGetId([
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
        $position = (int) ($entry['position'] ?? 0);
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
            return (int) $existing;
        }

        return (int) DB::table($table)->insertGetId([$column => $value], 'id');
    }

    private function text(mixed $value): ?string
    {
        if (!is_string($value)) {
            return null;
        }

        return trim($value) === '' ? null : trim($value);
    }

    /** @param mixed $value */
    private function pgArray(mixed $value): ?string
    {
        if (!is_array($value)) {
            return null;
        }
        $parts = [];
        foreach ($value as $element) {
            if ($element === null) {
                $parts[] = 'NULL';
                continue;
            }
            $parts[] = '"' . str_replace(['\\', '"'], ['\\\\', '\\"'], (string) $element) . '"';
        }

        return '{' . implode(',', $parts) . '}';
    }
}
