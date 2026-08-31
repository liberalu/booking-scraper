<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Casts\PostgresTextArray;
use App\Parsers\Ibiblioteka\Parser;
use App\Repositories\CanonicalBookRepository;
use App\Support\Database;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

final class CanonicalBookCharacterisationTest extends TestCase
{
    private const GOLDEN = __DIR__.'/../golden/canonical_expected.json';

    private const FIXTURES = __DIR__.'/../fixtures/ibiblioteka/canonical';

    #[Group('db')]
    public function test_each_frozen_record_still_writes_the_same_rows(): void
    {
        $golden = self::golden();

        Database::boot(getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');

        DB::beginTransaction();
        try {
            $urls = array_column($golden['records'], 'url');

            DB::delete('delete from books where source_url = any(?)', ['{'.implode(',', $urls).'}']);

            foreach ($golden['records'] as $record) {
                $path = self::FIXTURES.'/'.$record['fixture'];
                self::assertFileExists($path, "missing frozen record: {$record['fixture']}");

                $parsed = Parser::parseProductPage((string) file_get_contents($path));
                self::assertSame(
                    'book',
                    $parsed['_emit_as'] ?? null,
                    'the parser stopped tagging this as a canonical book — it would '
                    .'be stored as a shop_book instead'
                );
                $parsed['source_url'] = $record['url'];

                (new CanonicalBookRepository)->upsert($parsed);
            }

            self::assertEquals($golden['expected'], self::snapshot($urls));
        } finally {
            DB::rollBack();
        }
    }

    #[Group('db')]
    public function test_reapplying_a_record_is_idempotent(): void
    {
        $golden = self::golden();

        Database::boot(getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');

        DB::beginTransaction();
        try {
            $urls = array_column($golden['records'], 'url');
            DB::delete('delete from books where source_url = any(?)', ['{'.implode(',', $urls).'}']);

            foreach ([1, 2] as $_pass) {
                foreach ($golden['records'] as $record) {
                    $parsed = Parser::parseProductPage(
                        (string) file_get_contents(self::FIXTURES.'/'.$record['fixture'])
                    );
                    $parsed['source_url'] = $record['url'];
                    (new CanonicalBookRepository)->upsert($parsed);
                }
            }

            self::assertEquals(
                $golden['expected'],
                self::snapshot($urls),
                'a second pass changed the rows — the upsert is not idempotent'
            );
        } finally {
            DB::rollBack();
        }
    }

    private static function decodeArrays(object $row): array
    {
        $out = (array) $row;
        foreach (['translated_from', 'udc_codes', 'subjects'] as $column) {
            if (is_string($out[$column] ?? null)) {
                $out[$column] = PostgresTextArray::parse($out[$column]);
            }
        }

        return $out;
    }

    private static function snapshot(array $urls): array
    {
        $array = '{'.implode(',', $urls).'}';

        return [

            'books' => array_map(self::decodeArrays(...), DB::select(
                'select b.source_url, b.libis_code, b.data_source, b.title,
                        b.title_full, b.year, b.release_place, b.type, b.format,
                        b.pages, b.duration, b.dimensions, b.language,
                        b.translated_from, b.description, b.cover_url,
                        b.upcoming_release, b.udc_codes, b.subjects, b.audience,
                        b.libis_rating, b.libis_review_count,
                        p.name as publisher, s.title as series
                   from books b
                   left join publishers p on p.id = b.publisher_id
                   left join series s on s.id = b.series_id
                  where b.source_url = any(?) order by b.source_url', [$array]
            )),
            'isbns' => array_map(fn (object $r): array => array_values((array) $r), DB::select(
                'select b.source_url, i.isbn, i.isbn_type from book_isbns i
                   join books b on b.id = i.book_id
                  where b.source_url = any(?) order by b.source_url, i.isbn', [$array]
            )),
            'authors' => array_map(fn (object $r): array => array_values((array) $r), DB::select(
                'select b.source_url, a.name, a.normalized_name,
                        a.libis_code as author_libis, ba.role, ba.position
                   from book_authors ba
                   join books b on b.id = ba.book_id
                   join authors a on a.id = ba.author_id
                  where b.source_url = any(?)
                  order by b.source_url, ba.position, a.name, ba.role', [$array]
            )),
        ];
    }

    private static function golden(): array
    {
        self::assertFileExists(self::GOLDEN, 'run `make canonical-diff FREEZE=1` first');

        return json_decode((string) file_get_contents(self::GOLDEN), true, 512, JSON_THROW_ON_ERROR);
    }
}
