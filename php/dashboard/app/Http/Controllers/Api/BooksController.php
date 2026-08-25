<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\Queries;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Symfony\Component\HttpFoundation\StreamedResponse;
use Illuminate\Support\Facades\DB;

/**
 * The canonical `books` table — shop-independent records, populated by the
 * match phase. Distinct from shop-books, which is one row per
 * book-as-it-appears-in-a-shop.
 */
final class BooksController
{
    /** Books whose linked shop_books disagree on metadata. */
    private const CONFLICT_HAVING = 'count(distinct lower(title)) > 1'
        . ' or count(distinct lower(author)) > 1'
        . ' or count(distinct year) > 1'
        . ' or count(distinct lower(publisher)) > 1';

    public function index(Request $request): array
    {
        $page = max(1, (int) $request->query('page', 1));
        $perPage = max(1, min((int) $request->query('per_page', 50), 200));

        $query = DB::table('books');

        if (($source = $request->query('data_source')) !== null) {
            $query->where('data_source', $source);
        }
        if (($year = $request->query('year')) !== null && $year !== '') {
            $query->where('year', (int) $year);
        }
        if ($request->has('has_isbn')) {
            $withIsbn = DB::table('book_isbns')->select('book_id')->distinct();
            $request->boolean('has_isbn')
                ? $query->whereIn('id', $withIsbn)
                : $query->whereNotIn('id', $withIsbn);
        }
        if ($request->has('has_shops')) {
            $linked = DB::table('shop_books')->select('book_id')->whereNotNull('book_id')->distinct();
            $request->boolean('has_shops')
                ? $query->whereIn('id', $linked)
                : $query->whereNotIn('id', $linked);
        }
        if ($request->has('has_conflicts')) {
            $conflicting = DB::table('shop_books')
                ->select('book_id')
                ->whereNotNull('book_id')
                ->groupBy('book_id')
                ->havingRaw(self::CONFLICT_HAVING);
            $request->boolean('has_conflicts')
                ? $query->whereIn('id', $conflicting)
                : $query->whereNotIn('id', $conflicting);
        }

        $min = $request->query('shop_count_min');
        $max = $request->query('shop_count_max');
        if ($min !== null || $max !== null) {
            $counts = DB::table('shop_books')
                ->select('book_id')
                ->whereNotNull('book_id')
                ->groupBy('book_id');
            if ($min !== null) {
                $counts->havingRaw('count(id) >= ?', [(int) $min]);
            }
            if ($max !== null) {
                $counts->havingRaw('count(id) <= ?', [(int) $max]);
            }
            $query->whereIn('id', $counts);
        }

        $search = trim((string) $request->query('search', ''));
        if ($search !== '') {
            // An ISBN-shaped query is an EXACT lookup — substring-matching a
            // 13-digit code returns noise, and the caller clearly wants one
            // book. Everything else matches title or author name.
            $isbn = self::asIsbn($search);
            if ($isbn !== null) {
                $query->whereIn(
                    'id',
                    DB::table('book_isbns')->select('book_id')->where('isbn', $isbn)
                );
            } else {
                $like = "%{$search}%";
                $query->where(function ($sub) use ($like): void {
                    $sub->where('title', 'ilike', $like)
                        ->orWhereIn('id', DB::table('book_authors')
                            ->join('authors', 'authors.id', '=', 'book_authors.author_id')
                            ->select('book_authors.book_id')
                            ->where('authors.name', 'ilike', $like));
                });
            }
        }

        $total = (clone $query)->count();
        // created_at, not id: ordering by id would put back-filled canonical
        // records ahead of newly matched ones.
        $books = $query->orderByDesc('created_at')
            ->orderByDesc('id')
            ->offset(($page - 1) * $perPage)
            ->limit($perPage)
            ->get();

        return [
            'books' => $this->decorate($books->all()),
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            // NOT Queries::pageCount(): queries.py::list_books omits the
            // max(1, ...) floor that every other handler applies, so an empty
            // result reports 0 pages here and 1 everywhere else.
            'pages' => $perPage ? intdiv($total + $perPage - 1, $perPage) : 1,
        ];
    }

    /**
     * Attach the per-book aggregates the list shows. Batched by id rather
     * than queried per row: the page renders 50 books and per-row lookups
     * would be 200 round trips.
     *
     * @param  list<object>  $books
     * @return list<array<string, mixed>>
     */
    private function decorate(array $books): array
    {
        if ($books === []) {
            return [];
        }
        $ids = array_map(static fn (object $b): int => (int) $b->id, $books);

        // No ORDER BY, deliberately: `primary_isbn` is whichever row the
        // planner returns first, and Python's query is unordered too.
        // 138,033 books have more than one ISBN, so imposing an order here
        // would pick a different "primary" than the Python dashboard shows
        // for the same book.
        $isbns = DB::table('book_isbns')
            ->select('book_id', 'isbn')
            ->whereIn('book_id', $ids)
            ->get()
            ->groupBy('book_id');

        // role = 'author' only. book_authors also holds translators,
        // narrators and illustrators, and without the filter authors[0] can
        // be a translator — which is what the CSV export puts in its
        // `author` column.
        $authors = DB::table('book_authors')
            ->join('authors', 'authors.id', '=', 'book_authors.author_id')
            ->select('book_authors.book_id', 'authors.name')
            ->whereIn('book_authors.book_id', $ids)
            ->where('book_authors.role', 'author')
            ->orderBy('book_authors.position')
            ->get()
            ->groupBy('book_id');

        $shopStats = DB::table('shop_books')
            ->select('book_id')
            ->selectRaw('count(id) as shop_count, min(price) as price_min, max(price) as price_max')
            ->whereIn('book_id', $ids)
            ->groupBy('book_id')
            ->get()
            ->keyBy('book_id');

        $conflicting = DB::table('shop_books')
            ->select('book_id')
            ->whereIn('book_id', $ids)
            ->groupBy('book_id')
            ->havingRaw(self::CONFLICT_HAVING)
            ->pluck('book_id')
            ->all();
        $conflicting = array_fill_keys($conflicting, true);

        $publishers = DB::table('publishers')->pluck('name', 'id');

        return array_map(function (object $book) use ($isbns, $authors, $shopStats, $conflicting, $publishers): array {
            $stats = $shopStats[$book->id] ?? null;

            return [
                'id' => (int) $book->id,
                'title' => $book->title,
                'year' => $book->year,
                'data_source' => $book->data_source,
                'libis_code' => $book->libis_code,
                'publisher' => $book->publisher_id !== null
                    ? ($publishers[$book->publisher_id] ?? null)
                    : null,
                'primary_isbn' => ($isbns[$book->id][0]->isbn ?? null),
                'authors' => array_values(array_map(
                    static fn (object $a): string => $a->name,
                    ($authors[$book->id] ?? collect())->all()
                )),
                'shop_count' => (int) ($stats->shop_count ?? 0),
                'price_min' => $stats?->price_min !== null ? (float) $stats->price_min : null,
                'price_max' => $stats?->price_max !== null ? (float) $stats->price_max : null,
                'has_conflicts' => isset($conflicting[$book->id]),
            ];
        }, $books);
    }

    /** KPI strip for the books page. */
    public function stats(): array
    {
        $total = DB::table('books')->count();
        $enriched = DB::table('books')->where('data_source', '!=', 'shop_inferred')->count();

        // Shop counts per book, for books that have any listing at all.
        $counts = DB::table('shop_books')
            ->select('book_id')
            ->selectRaw('count(id) as n')
            ->whereNotNull('book_id')
            ->groupBy('book_id')
            ->pluck('n')
            ->all();

        $multiShop = count(array_filter($counts, static fn (int $n): bool => $n >= 2));
        $singleShop = count(array_filter($counts, static fn (int $n): bool => $n === 1));
        $listings = array_sum($counts);

        $conflicts = DB::table(DB::raw('(' . DB::table('shop_books')
            ->select('book_id')
            ->whereNotNull('book_id')
            ->groupBy('book_id')
            ->havingRaw(self::CONFLICT_HAVING)
            ->toSql() . ') as c'))->count();

        return [
            'total' => $total,
            'enriched' => $enriched,
            'enriched_pct' => $total > 0 ? round($enriched / $total * 100, 1) : 0,
            'multi_shop' => $multiShop,
            'single_shop' => $singleShop,
            'avg_shops' => $counts !== [] ? round($listings / count($counts), 1) : 0,
            'conflicts' => $conflicts,
        ];
    }

    /**
     * The normalised ISBN when the input looks like one, else null.
     *
     * Dashes and spaces stripped, X uppercased. Accepts ISBN-10 (optional
     * trailing X) and ISBN-13.
     */
    private static function asIsbn(string $value): ?string
    {
        $normalized = strtoupper(str_replace(['-', ' '], '', $value));

        return preg_match('/^(?:\d{9}[\dX]|\d{13})$/', $normalized) === 1
            ? $normalized
            : null;
    }

    /** Distinct publication years, newest first — populates a filter. */
    public function years(): array
    {
        return DB::table('books')
            ->whereNotNull('year')
            ->distinct()
            ->orderByDesc('year')
            ->pluck('year')
            ->map(fn ($y): int => (int) $y)
            ->all();
    }

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function show(int $bookId): mixed
    {
        $book = DB::table('books')->where('id', $bookId)->first();
        if ($book === null) {
            return response()->json(['detail' => 'Book not found'], 404);
        }

        $isbns = DB::table('book_isbns')
            ->select('isbn', 'isbn_type')
            ->where('book_id', $bookId)
            ->get()
            ->map(fn (object $r): array => ['isbn' => $r->isbn, 'type' => $r->isbn_type])
            ->all();

        $authors = DB::table('book_authors')
            ->join('authors', 'authors.id', '=', 'book_authors.author_id')
            ->select('authors.name', 'book_authors.role')
            ->where('book_authors.book_id', $bookId)
            ->orderBy('book_authors.role')
            ->orderBy('book_authors.position')
            ->get()
            ->map(fn (object $r): array => ['name' => $r->name, 'role' => $r->role])
            ->all();

        $shops = DB::table('shop_books')
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

        // Earliest first_seen_at across every linked shop — when this book
        // first entered the catalogue anywhere.
        $firstSeen = $shops
            ->pluck('first_seen_at')
            ->filter()
            ->map(fn (string $t): string => (string) $t)
            ->sort()
            ->first();

        [$scrapedUrl, $pageUrl] = self::ibibliotekaUrls($book);

        return [
            'id' => (int) $book->id,
            'title' => $book->title,
            'title_full' => $book->title_full,
            'data_source' => $book->data_source,
            'libis_code' => $book->libis_code,
            'year' => $book->year,
            'publisher' => $book->publisher_id !== null
                ? DB::table('publishers')->where('id', $book->publisher_id)->value('name')
                : null,
            'series' => $book->series_id !== null
                ? DB::table('series')->where('id', $book->series_id)->value('title')
                : null,
            'release_place' => $book->release_place,
            'type' => $book->type,
            'format' => $book->format,
            'pages' => $book->pages,
            'duration' => $book->duration,
            'dimensions' => $book->dimensions,
            'language' => $book->language,
            'translated_from' => self::pgArray($book->translated_from),
            'description' => $book->description,
            'cover_url' => $book->cover_url,
            'udc_codes' => self::pgArray($book->udc_codes),
            'subjects' => self::pgArray($book->subjects),
            'audience' => $book->audience,
            'isbns' => $isbns,
            'authors' => $authors,
            'first_matched_at' => $firstSeen !== null ? self::iso($firstSeen) : null,
            'scraped_url' => $scrapedUrl,
            'ibiblioteka_page_url' => $pageUrl,
            'shops' => $shops->map(fn (object $row): array => [
                'shop' => $row->name,
                'shop_book_id' => (int) $row->shop_book_id,
                'url' => $row->url,
                'price' => $row->price !== null ? (string) $row->price : null,
                'in_stock' => (bool) $row->in_stock,
                'last_seen_at' => self::iso($row->last_seen_at),
                'first_seen_at' => self::iso($row->first_seen_at),
                'is_active' => (bool) $row->is_active,
                'match_status' => $row->match_status,
                'title' => $row->shop_title,
                'author' => $row->shop_author,
                'year' => $row->shop_year,
                'isbn' => $row->shop_isbn,
                'publisher' => $row->shop_publisher,
                'format' => $row->shop_format,
                'match_method' => $row->match_method,
            ])->all(),
        ];
    }

    /**
     * 30-day daily price series per shop linked to the book.
     *
     * Sparse on purpose: days with no scrape are omitted rather than
     * back-filled, so a gap in the chart reads as "we didn't look".
     *
     * @return array<string, mixed>|\Illuminate\Http\JsonResponse
     */
    public function prices(int $bookId): mixed
    {
        if (!DB::table('books')->where('id', $bookId)->exists()) {
            return response()->json(['detail' => 'Book not found'], 404);
        }

        $rows = DB::table('prices')
            ->join('shop_books', 'shop_books.id', '=', 'prices.shop_book_id')
            ->join('shops', 'shops.id', '=', 'shop_books.shop_id')
            ->selectRaw("shops.name as shop, date_trunc('day', prices.scraped_at) as day, max(prices.price) as price")
            ->where('shop_books.book_id', $bookId)
            ->where('prices.scraped_at', '>=', Carbon::now('UTC')->subDays(30))
            ->groupBy('shops.name', DB::raw("date_trunc('day', prices.scraped_at)"))
            ->orderBy('shops.name')
            ->orderBy(DB::raw("date_trunc('day', prices.scraped_at)"))
            ->get();

        $series = [];
        foreach ($rows as $row) {
            $series[$row->shop][] = [
                'date' => Carbon::parse($row->day)->format('Y-m-d'),
                'price' => (float) $row->price,
            ];
        }

        return [
            'book_id' => $bookId,
            'series' => array_map(
                static fn (string $shop, array $points): array => ['shop' => $shop, 'series' => $points],
                array_keys($series),
                array_values($series)
            ),
        ];
    }

    /**
     * The API endpoint the record came from, and its human-readable page.
     *
     * The publication route accepts the record code as well as the numeric
     * API id, so libis_code covers books with no stored source_url.
     *
     * @return array{0: string|null, 1: string|null}
     */
    private static function ibibliotekaUrls(object $book): array
    {
        $scrapedUrl = $book->source_url;
        $pageUrl = null;

        if ($book->data_source === 'ibiblioteka' && $book->libis_code) {
            $pageUrl = "https://ibiblioteka.lt/metis/publication/{$book->libis_code}";
            $scrapedUrl ??= 'https://ibiblioteka.lt/metis-api/bibliographic-records/public/'
                . $book->libis_code;
        } elseif ($scrapedUrl) {
            $last = basename(rtrim($scrapedUrl, '/'));
            if (ctype_digit($last)) {
                $pageUrl = "https://ibiblioteka.lt/metis/publication/{$last}";
            }
        }

        return [$scrapedUrl, $pageUrl];
    }

    /** @return list<string>|null */
    private static function pgArray(mixed $value): ?array
    {
        if ($value === null) {
            return null;
        }

        return \BookScraper\Casts\PostgresTextArray::parse((string) $value);
    }

    /**
     * A price as Python's csv writer renders it.
     *
     * Two behaviours to match: `value or ""` blanks a 0.0 price, and
     * str(float) renders a whole number as "40.0" where PHP gives "40".
     */
    private static function csvNumber(mixed $value): string
    {
        if ($value === null || (float) $value === 0.0) {
            return '';
        }
        $float = (float) $value;

        return $float === floor($float) && is_finite($float)
            ? sprintf('%.1f', $float)
            : (string) $float;
    }

    private static function iso(mixed $timestamp): ?string
    {
        if ($timestamp === null) {
            return null;
        }
        $dt = Carbon::parse($timestamp)->utc();

        return $dt->micro === 0
            ? $dt->format('Y-m-d\TH:i:sP')
            : $dt->format('Y-m-d\TH:i:s.uP');
    }

    /**
     * GET /api/books/export — CSV of every book matching the filters.
     *
     * Streamed and paged at 500: the unfiltered catalogue is ~50k rows, and
     * building the whole file in memory before sending would spike the
     * dashboard's footprint on a click.
     */
    public function export(Request $request): StreamedResponse
    {
        $columns = [
            'id', 'title', 'author', 'isbn', 'year', 'publisher',
            'shop_count', 'price_min', 'price_max', 'data_source', 'has_conflicts',
        ];

        return response()->streamDownload(function () use ($request, $columns): void {
            $handle = fopen('php://output', 'wb');
            // \r\n to match Python's csv.writer default; the frontend and
            // Excel both accept it, and a mismatch makes every line differ.
            fputcsv($handle, $columns, ',', '"', '\\', "\r\n");

            $page = 1;
            $perPage = 500;
            do {
                $request->merge(['page' => $page, 'per_page' => $perPage]);
                $result = $this->index($request);

                foreach ($result['books'] as $book) {
                    fputcsv($handle, [
                        $book['id'],
                        $book['title'],
                        $book['authors'][0] ?? '',
                        $book['primary_isbn'] ?: '',
                        // Python writes `value or ""`, so a falsy value —
                        // including year 0 — becomes blank.
                        $book['year'] ?: '',
                        $book['publisher'] ?: '',
                        $book['shop_count'],
                        self::csvNumber($book['price_min']),
                        self::csvNumber($book['price_max']),
                        $book['data_source'] ?: '',
                        $book['has_conflicts'] ? 'yes' : 'no',
                    ], ',', '"', '\\', "\r\n");
                }
                // Flush per page so the browser starts receiving immediately.
                flush();
                $page++;
            } while ($page <= ($result['pages'] ?? 1));

            fclose($handle);
        }, 'books.csv', ['Content-Type' => 'text/csv']);
    }

    /**
     * Create a canonical book by hand (data_source='manual').
     *
     * The ISBN is checked for uniqueness across the whole catalogue, not
     * just this book — `book_isbns.isbn` is globally unique, so a collision
     * has to be reported rather than left to blow up as a 500.
     *
     * @return array<string, mixed>|\Illuminate\Http\JsonResponse
     */
    public function store(Request $request): mixed
    {
        $title = trim((string) $request->input('title', ''));
        if ($title === '') {
            return response()->json(['detail' => 'title is required'], 422);
        }

        $isbn = null;
        $rawIsbn = trim((string) $request->input('isbn', ''));
        if ($rawIsbn !== '') {
            $isbn = self::normaliseIsbn($rawIsbn);
            if ($isbn === null) {
                return response()->json([
                    'detail' => 'Invalid ISBN format (expected 10 or 13 digits)',
                ], 422);
            }
        }

        if ($isbn !== null) {
            $owner = DB::table('book_isbns')->where('isbn', $isbn)->value('book_id');
            if ($owner !== null) {
                return response()->json([
                    'detail' => [
                        'message' => 'ISBN already belongs to another book.',
                        'existing_book_id' => (int) $owner,
                    ],
                ], 409);
            }
        }

        $year = $request->input('year');
        $author = (string) $request->input('author', '');
        $publisher = (string) $request->input('publisher', '');

        $bookId = DB::transaction(static function () use (
            $title,
            $isbn,
            $author,
            $publisher,
            $year
        ): int {
            $publisherId = null;
            if (trim($publisher) !== '') {
                $name = trim($publisher);
                $publisherId = DB::table('publishers')->where('name', $name)->value('id');
                $publisherId = $publisherId !== null
                    ? (int) $publisherId
                    : (int) DB::table('publishers')->insertGetId(['name' => $name], 'id');
            }

            $bookId = (int) DB::table('books')->insertGetId([
                'data_source' => 'manual',
                'title' => $title,
                'year' => $year === null || $year === '' ? null : (int) $year,
                'publisher_id' => $publisherId,
            ], 'id');

            if ($isbn !== null) {
                DB::table('book_isbns')->insert([
                    'book_id' => $bookId,
                    'isbn' => $isbn,
                    'isbn_type' => strlen($isbn) === 13 ? 'isbn13' : 'isbn10',
                ]);
            }

            if (trim($author) !== '') {
                $name = trim($author);
                // Dedup key is the whitespace-collapsed lowercase name.
                $normalised = preg_replace('/\s+/', ' ', mb_strtolower($name)) ?? $name;
                $authorId = DB::table('authors')
                    ->where('normalized_name', $normalised)
                    ->value('id');
                $authorId = $authorId !== null
                    ? (int) $authorId
                    : (int) DB::table('authors')->insertGetId([
                        'name' => $name,
                        'normalized_name' => $normalised,
                    ], 'id');
                DB::table('book_authors')->insert([
                    'book_id' => $bookId,
                    'author_id' => $authorId,
                    'role' => 'author',
                    'position' => 0,
                ]);
            }

            return $bookId;
        });

        return ['id' => $bookId, 'title' => $title];
    }

    /**
     * Digits-only ISBN-10 (optional trailing X) or ISBN-13, or null.
     *
     * Deliberately a shape check, not a checksum one — Python's
     * `_looks_like_isbn` accepts any 13 digits.
     */
    private static function normaliseIsbn(string $value): ?string
    {
        $normalised = strtoupper(str_replace(['-', ' '], '', $value));
        if ($normalised === '') {
            return null;
        }

        return preg_match('/^(?:\d{9}[\dX]|\d{13})$/', $normalised) === 1
            ? $normalised
            : null;
    }
}
