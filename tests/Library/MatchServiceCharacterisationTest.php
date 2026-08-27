<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Support\Database;
use App\Services\MatchService;
use App\Testing\SyntheticShop;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

/**
 * The matcher's linkage, pinned to what Python produced.
 *
 * `make match-diff` runs both matchers over identical data and compares the
 * resulting linkage — which needs Python. `match_diff --freeze` writes the
 * golden only once both matchers agreed.
 *
 * Frozen over the SYNTHETIC shop, and only over it: a copied shop's linkage
 * depends on which canonicals the copy happens to carry, and the copy moves
 * with the catalogue. SyntheticShop owns the canonical its books link to, and
 * refuses to build if any of its ISBNs already belongs to something else — the
 * first draft used plausible 978-609 numbers, three of which existed in the
 * copied catalogue, and the linkage was therefore not reproducible.
 *
 * Two rows carry the interesting cases: `matchable` is unmatched with an ISBN
 * whose canonical exists (step 1 links it, step 2 backfills its author), and
 * `drift` is already linked to a canonical whose ISBN disagrees — which the
 * matcher must leave exactly as it found it. That second one is the whole
 * reason match_isbn_drift is stale state rather than a matcher bug, so it is
 * worth a regression test.
 *
 * Step 3 (synthesis) is NOT frozen: it creates canonicals, so a second run
 * over the same fixture has nothing left to synthesise.
 *
 * Nothing is keyed by id — ids change on every rebuild. Books are keyed by
 * URL, authors by name, synthesised books by ISBN.
 */
final class MatchServiceCharacterisationTest extends TestCase
{
    private const GOLDEN = __DIR__ . '/golden/match_linkage.json';

    #[Group('db')]
    public function testTheLinkageIsTheOnePythonProduced(): void
    {
        $expected = json_decode((string) file_get_contents(self::GOLDEN), true);
        self::assertIsArray($expected, 'golden is missing — run `make match-diff FREEZE=1 SHOP=synthetic`');

        Database::boot(getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');

        DB::beginTransaction();
        try {
            SyntheticShop::build(DB::connection());

            // Taken after the build: the fixture creates canonicals of its
            // own, and they are not what "synthesised" means here.
            $maxBook = (int) DB::table('books')->max('id');

            (new MatchService())->run(SyntheticShop::SHOP, false);

            self::assertSame($expected, $this->linkage($maxBook));
        } finally {
            DB::rollBack();
        }
    }

    /**
     * Mirrors result_state() in php/tools/match_diff.py — same columns, same
     * order, same keys, so the golden it writes is the structure read here.
     *
     * @return array<string, list<array<string, mixed>>>
     */
    private function linkage(int $maxBook): array
    {
        $books = array_map(static fn ($r): array => [
            'linked' => (bool) $r->linked,
            'match_method' => $r->match_method,
            'match_status' => $r->match_status,
            'url' => $r->url,
        ], DB::select(
            'select sb.url, sb.book_id is not null as linked, sb.match_status, '
            . 'sb.match_method from shop_books sb join shops s on s.id = sb.shop_id '
            . 'where s.name = ? order by sb.url',
            [SyntheticShop::SHOP]
        ));

        $authors = array_map(static fn ($r): array => [
            'canonical_name' => $r->canonical_name,
            'name' => $r->name,
        ], DB::select(
            // Scoped to this shop: shop_authors carries no shop of its own,
            // so an unscoped query returns every shop's links and the copied
            // catalogue's authors leak into a fixture's golden.
            'select distinct sa.name, a.name as canonical_name from shop_authors sa '
            . 'join authors a on a.id = sa.canonical_author_id '
            . 'join shop_book_authors sba on sba.author_id = sa.id '
            . 'join shop_books sb on sb.id = sba.shop_book_id '
            . 'join shops s on s.id = sb.shop_id where s.name = ? '
            . 'order by sa.name, a.name',
            [SyntheticShop::SHOP]
        ));

        $synthesised = array_map(static fn ($r): array => [
            'format' => $r->format,
            'isbn' => $r->isbn,
            'publisher' => $r->publisher,
            'title' => $r->title,
            'type' => $r->type,
            'year' => $r->year,
        ], DB::select(
            'select bi.isbn, b.title, b.year, b.type, b.format, p.name as publisher '
            . 'from books b join book_isbns bi on bi.book_id = b.id '
            . 'left join publishers p on p.id = b.publisher_id '
            . 'where b.id > ? order by bi.isbn',
            [$maxBook]
        ));

        return [
            'author_links' => $authors,
            'shop_books' => $books,
            'synthesised' => $synthesised,
        ];
    }
}
