<?php

declare(strict_types=1);

namespace BookScraper\Services;

use BookScraper\Config;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Throwable;

/**
 * Match step 1, ported from book_scraper/services/match.py.
 *
 * Linkage is strictly ISBN-exact. Nothing here infers a match from title or
 * author — when `match_isbn_drift` fires it means the shop_book's ISBN
 * changed after the link was made, not that the matcher guessed wrong.
 *
 * The `book_id IS NULL` guard is why drift persists: an existing link is
 * never re-evaluated, so a corrupted ISBN has to be unlinked (the upsert's
 * drift guard does that) before this can re-link it.
 */
final class MatchService
{
    /** Trust for a shop with no `[match] trust` in its TOML. */
    private const DEFAULT_TRUST = 50;

    /** @var array<string, int> */
    private array $trustCache = [];

    /**
     * Run every match step for one shop.
     *
     * Step 3 (synthesis) is off by default, matching MATCH_SYNTHESIS_ENABLED
     * on the Python side: the per-row synthesis loop on a shop with ~2.5k
     * unmatched books blocked the reactor past the heartbeat reaper and
     * killed steps 1 and 2 mid-transaction. PHP does not share that
     * constraint, but the flag stays so both stacks default alike.
     *
     * @return array{books_linked: int, authors_linked: int, books_synthesized: int}
     */
    public function run(string $shopName, ?bool $synthesis = null): array
    {
        $synthesis ??= (getenv('MATCH_SYNTHESIS_ENABLED') ?: '0') === '1';

        $booksLinked = $this->isbnMatch($shopName);
        $authorsLinked = $this->authorBackfill($shopName);
        $synthesised = 0;

        if ($synthesis) {
            $synthesised = $this->synthesise();
            // Re-run step 1 so the books just synthesised pick up their
            // matches in the same pass.
            $booksLinked += $this->isbnMatch($shopName);
        }

        return [
            'books_linked' => $booksLinked,
            'authors_linked' => $authorsLinked,
            'books_synthesized' => $synthesised,
        ];
    }

    /** Links shop_books to canonical books by exact ISBN. Returns rows updated. */
    public function isbnMatch(string $shopName): int
    {
        return DB::update(
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

    /**
     * Link shop_authors to canonical authors for books that matched in
     * step 1.
     *
     * The `role = 'author'` filter is load-bearing: book_authors also holds
     * translators, narrators and illustrators, each with its own position
     * sequence, so without it position 0 of the shop's author list would
     * collide with position 0 of the translators.
     *
     * min(author_id): a shop_author appears on many shop_books, whose
     * canonicals can name different authors at the same position, so the join
     * has several candidates and Postgres picked one arbitrarily. Both stacks
     * did, which made this step unreproducible — two runs over identical data
     * disagreed on thousands of rows, and the differential only passed because
     * the column was already populated and the IS NULL guard skipped the work.
     * min() is still an arbitrary choice among equally valid candidates, but
     * it is the SAME one every time.
     *
     * Returns rows updated.
     */
    public function authorBackfill(string $shopName): int
    {
        return DB::update(
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

    /**
     * Synthesise `shop_inferred` canonical books for ISBNs that have none.
     *
     * One shop is enough: a valid ISBN from any source describes a real
     * book. An earlier ≥2-shop guard blocked every legitimate synthesis,
     * because in practice all unmatched ISBNs are single-shop.
     *
     * Returns the number of books created.
     */
    public function synthesise(): int
    {
        $candidates = DB::select(
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
            if ($this->synthesiseOne((string) $row->isbn)) {
                $synthesised++;
            }
        }

        return $synthesised;
    }

    /**
     * Build one canonical book from the highest-trust shop's metadata, with
     * the FIRST writer's publisher.
     *
     * Two different tiebreaks on purpose: title/year/format come from the
     * shop we trust most, but the publisher is sticky to whichever shop saw
     * the book first — it changes less often and re-deciding it on every run
     * would churn the canonical record.
     */
    private function synthesiseOne(string $isbn): bool
    {
        $candidates = DB::select(
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

        $bookId = DB::table('books')->insertGetId([
            'data_source' => 'shop_inferred',
            'libis_code' => null,
            'title' => $winner->title ?: '(untitled)',
            'year' => $winner->year,
            'publisher_id' => $publisherId,
            'type' => $winner->type,
            'format' => $winner->format,
            'upcoming_release' => false,
            'created_at' => Carbon::now('UTC'),
            'updated_at' => Carbon::now('UTC'),
        ], 'id');

        DB::table('book_isbns')->insert([
            'book_id' => $bookId,
            'isbn' => $isbn,
            'isbn_type' => strlen($isbn) === 13 ? 'isbn13' : 'isbn10',
        ]);

        return true;
    }

    /** @param list<object> $candidates */
    private function highestTrust(array $candidates): object
    {
        usort($candidates, fn (object $a, object $b): int
            => $this->trust($b->shop_name) <=> $this->trust($a->shop_name));

        return $candidates[0];
    }

    /**
     * The publisher of whichever shop saw this book first, or null.
     *
     * @param list<object> $candidates
     */
    private function stickyPublisherId(array $candidates): ?int
    {
        $withPublisher = array_values(array_filter(
            $candidates,
            static fn (object $c): bool => !empty($c->publisher)
        ));
        if ($withPublisher === []) {
            return null;
        }

        // Rows with no first_seen_at sort last so they cannot win the
        // first-writer tiebreak by accident.
        usort($withPublisher, static function (object $a, object $b): int {
            $left = $a->first_seen_at ?? '9999-01-01';
            $right = $b->first_seen_at ?? '9999-01-01';

            return strcmp((string) $left, (string) $right);
        });

        $name = (string) $withPublisher[0]->publisher;
        $existing = DB::table('publishers')->where('name', $name)->value('id');
        if ($existing !== null) {
            return (int) $existing;
        }

        return (int) DB::table('publishers')->insertGetId(['name' => $name], 'id');
    }

    /**
     * Per-shop trust from `[match] trust` in the shop TOML.
     *
     * An unreadable config falls back to the default rather than killing the
     * matcher: one broken shop should not stop the rest of the catalogue.
     */
    private function trust(string $shopName): int
    {
        if (!array_key_exists($shopName, $this->trustCache)) {
            try {
                $this->trustCache[$shopName] = Config::forShop($shopName)->matchTrust();
            } catch (Throwable) {
                $this->trustCache[$shopName] = self::DEFAULT_TRUST;
            }
        }

        return $this->trustCache[$shopName];
    }
}
