<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Repositories\MatchingRepository;
use App\Services\MatchService;
use App\Support\Database;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;
use Tests\Support\SyntheticShop;

final class MatchServiceCharacterisationTest extends TestCase
{
    private const string GOLDEN = __DIR__.'/../golden/match_linkage.json';

    #[Group('db')]
    public function test_the_linkage_is_the_one_python_produced(): void
    {
        $expected = json_decode((string) file_get_contents(self::GOLDEN), true);
        self::assertIsArray($expected, 'golden is missing — run `make match-diff FREEZE=1 SHOP=synthetic`');

        Database::boot(getenv('TEST_DATABASE_URL')
            ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test');

        DB::beginTransaction();
        try {
            SyntheticShop::build(DB::connection());

            $maxBook = (int) DB::table('books')->max('id');

            (new MatchService(new MatchingRepository(Database::manager())))
                ->run(SyntheticShop::SHOP, false);

            self::assertSame($expected, $this->linkage($maxBook));
        } finally {
            DB::rollBack();
        }
    }

    private function linkage(int $maxBook): array
    {
        $books = array_map(static fn ($r): array => [
            'linked' => (bool) $r->linked,
            'match_method' => $r->match_method,
            'match_status' => $r->match_status,
            'url' => $r->url,
        ], DB::select(
            'select sb.url, sb.book_id is not null as linked, sb.match_status, '
            .'sb.match_method from shop_books sb join shops s on s.id = sb.shop_id '
            .'where s.name = ? order by sb.url',
            [SyntheticShop::SHOP]
        ));

        $authors = array_map(static fn ($r): array => [
            'canonical_name' => $r->canonical_name,
            'name' => $r->name,
        ], DB::select(

            'select distinct sa.name, a.name as canonical_name from shop_authors sa '
            .'join authors a on a.id = sa.canonical_author_id '
            .'join shop_book_authors sba on sba.author_id = sa.id '
            .'join shop_books sb on sb.id = sba.shop_book_id '
            .'join shops s on s.id = sb.shop_id where s.name = ? '
            .'order by sa.name, a.name',
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
            .'from books b join book_isbns bi on bi.book_id = b.id '
            .'left join publishers p on p.id = b.publisher_id '
            .'where b.id > ? order by bi.isbn',
            [$maxBook]
        ));

        return [
            'author_links' => $authors,
            'shop_books' => $books,
            'synthesised' => $synthesised,
        ];
    }
}
