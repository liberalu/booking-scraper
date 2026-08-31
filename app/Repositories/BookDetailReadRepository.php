<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Casts\PostgresTextArray;
use App\Models\Book;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use LogicException;

final class BookDetailReadRepository
{
    /** @return array<string, mixed> */
    public function show(Book $bookModel): array
    {
        $bookId = $bookModel->id;
        $rawBook = DB::table('books')->where('id', $bookId)->first();
        if ($rawBook === null) {
            throw new LogicException('Bound book is no longer available.');
        }
        $book = DatabaseRow::from($rawBook);

        $isbnRows = DB::table('book_isbns')
            ->select('isbn', 'isbn_type')
            ->where('book_id', $bookId)
            ->get();
        $isbns = [];
        foreach ($isbnRows as $raw) {
            $row = DatabaseRow::from($raw);
            $isbns[] = ['isbn' => $row->string('isbn'), 'type' => $row->string('isbn_type')];
        }
        $authorRows = DB::table('book_authors')
            ->join('authors', 'authors.id', '=', 'book_authors.author_id')
            ->select('authors.name', 'book_authors.role')
            ->where('book_authors.book_id', $bookId)
            ->orderBy('book_authors.role')
            ->orderBy('book_authors.position')
            ->get();
        $authors = [];
        foreach ($authorRows as $raw) {
            $row = DatabaseRow::from($raw);
            $authors[] = ['name' => $row->string('name'), 'role' => $row->string('role')];
        }
        $shopRows = DB::table('shop_books')
            ->join('shops', 'shops.id', '=', 'shop_books.shop_id')
            ->select(
                'shops.name',
                'shop_books.id as shop_book_id',
                'shop_books.url',
                'shop_books.price',
                'shop_books.in_stock',
                'shop_books.last_seen_at',
                'shop_books.first_seen_at',
                'shop_books.is_active',
                'shop_books.match_status',
                'shop_books.title as shop_title',
                'shop_books.author as shop_author',
                'shop_books.year as shop_year',
                'shop_books.isbn as shop_isbn',
                'shop_books.publisher as shop_publisher',
                'shop_books.format as shop_format',
                'shop_books.match_method',
            )
            ->where('shop_books.book_id', $bookId)
            ->orderBy('shops.name')
            ->get();
        $shops = [];
        $firstSeenValues = [];
        foreach ($shopRows as $raw) {
            $row = DatabaseRow::from($raw);
            $firstSeen = $row->nullableString('first_seen_at');
            if ($firstSeen !== null) {
                $firstSeenValues[] = $firstSeen;
            }
            $shops[] = [
                'shop' => $row->string('name'),
                'shop_book_id' => $row->int('shop_book_id'),
                'url' => $row->string('url'),
                'price' => $row->nullableString('price'),
                'in_stock' => $row->bool('in_stock'),
                'last_seen_at' => $this->iso($row->nullableString('last_seen_at')),
                'first_seen_at' => $this->iso($firstSeen),
                'is_active' => $row->bool('is_active'),
                'match_status' => $row->nullableString('match_status'),
                'title' => $row->nullableString('shop_title'),
                'author' => $row->nullableString('shop_author'),
                'year' => $row->nullableInt('shop_year'),
                'isbn' => $row->nullableString('shop_isbn'),
                'publisher' => $row->nullableString('shop_publisher'),
                'format' => $row->nullableString('shop_format'),
                'match_method' => $row->nullableString('match_method'),
            ];
        }
        sort($firstSeenValues);
        $firstSeen = $firstSeenValues[0] ?? null;
        [$scrapedUrl, $pageUrl] = $this->ibibliotekaUrls($book);

        return [
            'id' => $book->int('id'),
            'title' => $book->string('title'),
            'title_full' => $book->nullableString('title_full'),
            'data_source' => $book->string('data_source'),
            'libis_code' => $book->nullableString('libis_code'),
            'year' => $book->nullableInt('year'),
            'publisher' => $book->nullableInt('publisher_id') !== null
                ? $this->stringValue(DB::table('publishers')->where('id', $book->int('publisher_id'))->value('name'))
                : null,
            'series' => $book->nullableInt('series_id') !== null
                ? $this->stringValue(DB::table('series')->where('id', $book->int('series_id'))->value('title'))
                : null,
            'release_place' => $book->nullableString('release_place'),
            'type' => $book->nullableString('type'),
            'format' => $book->nullableString('format'),
            'pages' => $book->nullableInt('pages'),
            'duration' => $book->nullableString('duration'),
            'dimensions' => $book->nullableString('dimensions'),
            'language' => $book->nullableString('language'),
            'translated_from' => $this->pgArray($book->value('translated_from')),
            'description' => $book->nullableString('description'),
            'cover_url' => $book->nullableString('cover_url'),
            'udc_codes' => $this->pgArray($book->value('udc_codes')),
            'subjects' => $this->pgArray($book->value('subjects')),
            'audience' => $book->nullableString('audience'),
            'isbns' => $isbns,
            'authors' => $authors,
            'first_matched_at' => $firstSeen !== null ? $this->iso($firstSeen) : null,
            'scraped_url' => $scrapedUrl,
            'ibiblioteka_page_url' => $pageUrl,
            'shops' => $shops,
        ];
    }

    /** @return array<string, mixed> */
    public function prices(Book $book): array
    {
        $bookId = $book->id;
        $rows = DB::table('prices')
            ->join('shop_books', 'shop_books.id', '=', 'prices.shop_book_id')
            ->join('shops', 'shops.id', '=', 'shop_books.shop_id')
            ->selectRaw(
                "shops.name as shop, date_trunc('day', prices.scraped_at) as day,"
                .' max(prices.price) as price',
            )
            ->where('shop_books.book_id', $bookId)
            ->where('prices.scraped_at', '>=', Carbon::now('UTC')->subDays(30))
            ->groupBy('shops.name', DB::raw("date_trunc('day', prices.scraped_at)"))
            ->orderBy('shops.name')
            ->orderBy(DB::raw("date_trunc('day', prices.scraped_at)"))
            ->get();

        $series = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $series[$row->string('shop')][] = [
                'date' => Carbon::parse($row->string('day'))->format('Y-m-d'),
                'price' => $row->float('price'),
            ];
        }

        return [
            'book_id' => $bookId,
            'series' => array_map(
                static fn (string $shop, array $points): array => [
                    'shop' => $shop,
                    'series' => $points,
                ],
                array_keys($series),
                array_values($series),
            ),
        ];
    }

    /** @return array{string|null, string|null} */
    private function ibibliotekaUrls(DatabaseRow $book): array
    {
        $scrapedUrl = $book->nullableString('source_url');
        $pageUrl = null;
        $libisCode = $book->nullableString('libis_code');

        if ($book->string('data_source') === 'ibiblioteka' && $libisCode !== null && $libisCode !== '') {
            $pageUrl = "https://ibiblioteka.lt/metis/publication/{$libisCode}";
            $scrapedUrl ??= 'https://ibiblioteka.lt/metis-api/bibliographic-records/public/'
                .$libisCode;
        } elseif ($scrapedUrl !== null && $scrapedUrl !== '') {
            $last = basename(rtrim($scrapedUrl, '/'));
            if (ctype_digit($last)) {
                $pageUrl = "https://ibiblioteka.lt/metis/publication/{$last}";
            }
        }

        return [$scrapedUrl, $pageUrl];
    }

    /** @return list<string>|null */
    private function pgArray(mixed $value): ?array
    {
        return $value === null ? null : PostgresTextArray::parse($this->stringValue($value) ?? '');
    }

    private function iso(?string $timestamp): ?string
    {
        if ($timestamp === null) {
            return null;
        }

        $date = Carbon::parse($timestamp)->utc();

        return $date->micro === 0
            ? $date->format('Y-m-d\TH:i:sP')
            : $date->format('Y-m-d\TH:i:s.uP');
    }

    private function stringValue(mixed $value): ?string
    {
        return DatabaseRow::from(['value' => $value])->nullableString('value');
    }
}
