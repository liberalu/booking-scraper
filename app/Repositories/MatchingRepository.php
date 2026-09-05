<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Support\Config;
use Illuminate\Database\ConnectionInterface;
use Illuminate\Database\DatabaseManager;
use Illuminate\Support\Facades\Date;
use Throwable;

final class MatchingRepository
{
    private const int DEFAULT_TRUST = 50;

    /** @var array<string, int> */
    private array $trustCache = [];

    public function __construct(private readonly DatabaseManager $database) {}

    /** @return array{books_linked: int, authors_linked: int, books_synthesized: int} */
    public function run(string $shopName, ?bool $synthesis = null): array
    {
        $flag = getenv('MATCH_SYNTHESIS_ENABLED');
        $synthesis ??= ($flag === false ? '0' : $flag) === '1';

        $booksLinked = $this->isbnMatch($shopName);
        $authorsLinked = $this->authorBackfill($shopName);
        $synthesised = 0;

        if ($synthesis) {
            $synthesised = $this->synthesise();

            $booksLinked += $this->isbnMatch($shopName);
        }

        return [
            'books_linked' => $booksLinked,
            'authors_linked' => $authorsLinked,
            'books_synthesized' => $synthesised,
        ];
    }

    public function isbnMatch(string $shopName): int
    {
        return $this->connection()->update(
            "update shop_books sb
                set book_id = bi.book_id,
                    match_status = 'matched',
                    match_method = 'isbn'
               from book_isbns bi, shops s
              where sb.shop_id = s.id
                and s.name = ?
                and sb.isbn is not null
                and replace(replace(sb.isbn, '-', ''), ' ', '') = bi.isbn
                and sb.book_id is null",
            [$shopName]
        );
    }

    public function authorBackfill(string $shopName): int
    {
        return $this->connection()->update(
            "update shop_authors sa
                set canonical_author_id = c.author_id
               from (
                     select sba.author_id as shop_author_id,
                            min(ba.author_id) as author_id
                       from shop_book_authors sba
                       join shop_books sb on sb.id = sba.shop_book_id
                       join book_authors ba on ba.book_id = sb.book_id
                                           and ba.position = sba.position
                                           and ba.role = 'author'
                       join shops s on s.id = sb.shop_id
                      where sb.match_status = 'matched'
                        and s.name = ?
                      group by sba.author_id
                    ) c
              where sa.id = c.shop_author_id
                and sa.canonical_author_id is null",
            [$shopName]
        );
    }

    public function synthesise(): int
    {
        $candidates = $this->rows(
            "with candidates as (
                 select replace(replace(sb.isbn, '-', ''), ' ', '') as isbn
                   from shop_books sb
                  where sb.isbn is not null and sb.book_id is null
                  group by 1
             )
             select c.isbn
               from candidates c
              where not exists (select 1 from book_isbns bi where bi.isbn = c.isbn)"
        );

        $synthesised = 0;
        foreach ($candidates as $row) {
            if ($this->synthesiseOne($row->string('isbn'))) {
                $synthesised++;
            }
        }

        return $synthesised;
    }

    private function synthesiseOne(string $isbn): bool
    {
        $candidates = $this->rows(
            "select sb.id, sb.shop_id, s.name as shop_name, sb.title, sb.year,
                    sb.format, sb.type, sb.publisher, sb.first_seen_at
               from shop_books sb
               join shops s on s.id = sb.shop_id
              where replace(replace(sb.isbn, '-', ''), ' ', '') = ?",
            [$isbn]
        );

        if ($candidates === []) {
            return false;
        }

        $winner = $this->highestTrust($candidates);
        $publisherId = $this->stickyPublisherId($candidates);

        $bookId = $this->connection()->table('books')->insertGetId([
            'data_source' => 'shop_inferred',
            'libis_code' => null,
            'title' => $winner->nullableString('title') ?? '(untitled)',
            'year' => $winner->nullableInt('year'),
            'publisher_id' => $publisherId,
            'type' => $winner->nullableString('type'),
            'format' => $winner->nullableString('format'),
            'upcoming_release' => false,
            'created_at' => Date::now('UTC'),
            'updated_at' => Date::now('UTC'),
        ], 'id');

        $this->connection()->table('book_isbns')->insert([
            'book_id' => $bookId,
            'isbn' => $isbn,
            'isbn_type' => strlen($isbn) === 13 ? 'isbn13' : 'isbn10',
        ]);

        return true;
    }

    /**
     * @param  non-empty-list<DatabaseRow>  $candidates
     */
    private function highestTrust(array $candidates): DatabaseRow
    {
        usort($candidates, fn (DatabaseRow $a, DatabaseRow $b): int => $this->trust($b->string('shop_name')) <=> $this->trust($a->string('shop_name')));

        return $candidates[0];
    }

    /** @param list<DatabaseRow> $candidates */
    private function stickyPublisherId(array $candidates): ?int
    {
        $withPublisher = array_values(array_filter(
            $candidates,
            static fn (DatabaseRow $candidate): bool => $candidate->nullableString('publisher') !== null,
        ));
        if ($withPublisher === []) {
            return null;
        }

        usort($withPublisher, static function (DatabaseRow $a, DatabaseRow $b): int {
            $left = $a->nullableString('first_seen_at') ?? '9999-01-01';
            $right = $b->nullableString('first_seen_at') ?? '9999-01-01';

            return strcmp($left, $right);
        });

        $name = $withPublisher[0]->string('publisher');
        $existing = $this->connection()->table('publishers')->where('name', $name)->value('id');
        if ($existing !== null) {
            return DatabaseRow::from(['id' => $existing])->int('id');
        }

        return $this->connection()->table('publishers')->insertGetId(['name' => $name], 'id');
    }

    private function trust(string $shopName): int
    {
        if (! array_key_exists($shopName, $this->trustCache)) {
            try {
                $this->trustCache[$shopName] = Config::forShop($shopName)->matchTrust();
            } catch (Throwable) {
                $this->trustCache[$shopName] = self::DEFAULT_TRUST;
            }
        }

        return $this->trustCache[$shopName];
    }

    /**
     * @param  list<mixed>  $bindings
     * @return list<DatabaseRow>
     */
    private function rows(string $sql, array $bindings = []): array
    {
        return array_values(array_map(
            DatabaseRow::from(...),
            $this->connection()->select($sql, $bindings),
        ));
    }

    private function connection(): ConnectionInterface
    {
        return $this->database->connection();
    }
}
