<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Models\BookIsbn;
use App\Models\Shop;
use App\Models\ShopBook;
use App\Models\ShopBookAttribute;
use App\Repositories\ShopBookRepository;
use App\Support\Database;
use Illuminate\Database\Capsule\Manager as Capsule;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class ShopBookRepositoryTest extends TestCase
{
    private static ?Capsule $capsule = null;

    private ShopBookRepository $repo;

    private int $shopId;

    protected function setUp(): void
    {
        self::$capsule ??= Database::boot(
            getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test'
        );

        DB::beginTransaction();

        $this->repo = new ShopBookRepository;
        $this->shopId = Shop::firstOrCreate(
            ['name' => 'testshop'],
            ['base_url' => 'https://testshop.test']
        )->id;
    }

    protected function tearDown(): void
    {
        DB::rollBack();
    }

    public function test_creates_a_new_row(): void
    {
        $result = $this->repo->upsert($this->shopId, 'https://testshop.test/a', 'Book A', [
            'author' => 'Jane Doe',
            'isbn' => '9786090901595',
            'price' => '12.34',
            'in_stock' => true,
        ]);

        self::assertTrue($result->created);
        self::assertNull($result->oldPrice);
        self::assertSame([], $result->changes);
        self::assertSame('Book A', $result->shopBook->title);
        self::assertSame('created', $result->shopBook->last_run_action);
        self::assertTrue($result->shopBook->is_active);
    }

    public function test_normalizes_the_url_before_writing(): void
    {

        $first = $this->repo->upsert($this->shopId, 'https://testshop.test/b/', 'B');
        $second = $this->repo->upsert(
            $this->shopId,
            'https://testshop.test/b?utm_source=x',
            'B'
        );

        self::assertTrue($first->created);
        self::assertFalse($second->created);
        self::assertSame($first->shopBook->id, $second->shopBook->id);
    }

    public function test_tracks_changed_fields_and_returns_old_price(): void
    {
        $this->repo->upsert($this->shopId, 'https://testshop.test/c', 'Old Title', [
            'price' => '10.00',
            'publisher' => 'Old Pub',
        ]);

        $result = $this->repo->upsert($this->shopId, 'https://testshop.test/c', 'New Title', [
            'price' => '11.00',
            'publisher' => 'New Pub',
        ]);

        self::assertFalse($result->created);
        self::assertSame('10.00', $result->oldPrice);
        self::assertSame('updated', $result->shopBook->last_run_action);

        $byField = array_column($result->changes, null, 'field');
        self::assertSame(['old' => 'Old Title', 'new' => 'New Title', 'field' => 'title'],
            ['old' => $byField['title']['old'], 'new' => $byField['title']['new'], 'field' => 'title']);
        self::assertSame('Old Pub', $byField['publisher']['old']);
        self::assertSame('New Pub', $byField['publisher']['new']);
    }

    #[DataProvider('conditionalFields')]
    public function test_null_does_not_clobber_an_existing_value(string $field, mixed $value): void
    {

        $this->repo->upsert($this->shopId, 'https://testshop.test/d', 'D', [$field => $value]);
        $result = $this->repo->upsert($this->shopId, 'https://testshop.test/d', 'D', []);

        self::assertEquals($value, $result->shopBook->{$field});
        self::assertSame([], $result->changes);
    }

    public static function conditionalFields(): array
    {
        return [
            ['author', 'Kept Author'],
            ['isbn', '9786090901595'],
            ['publisher', 'Kept Publisher'],
            ['year', 2024],
            ['format', 'paperback'],
            ['description', 'Kept description'],
        ];
    }

    public function test_returning_book_clears_the_inactive_stamp(): void
    {
        $created = $this->repo->upsert($this->shopId, 'https://testshop.test/e', 'E');
        ShopBook::whereKey($created->shopBook->id)
            ->update(['is_active' => false, 'inactive_since' => Date::now('UTC')]);

        $result = $this->repo->upsert($this->shopId, 'https://testshop.test/e', 'E');

        self::assertTrue($result->shopBook->is_active);
        self::assertNull($result->shopBook->inactive_since);
    }

    public function test_sku_match_wins_over_url_so_a_slug_rename_updates_in_place(): void
    {
        $created = $this->repo->upsert($this->shopId, 'https://testshop.test/old-slug', 'F', [
            'sku' => 'SKU-1',
        ]);

        $result = $this->repo->upsert($this->shopId, 'https://testshop.test/new-slug', 'F', [
            'sku' => 'SKU-1',
        ]);

        self::assertFalse($result->created, 'a renamed slug must not create a second row');
        self::assertSame($created->shopBook->id, $result->shopBook->id);
        self::assertSame('https://testshop.test/new-slug', $result->shopBook->url);

        $urlChange = array_column($result->changes, null, 'field')['url'];
        self::assertSame('https://testshop.test/old-slug', $urlChange['old']);
    }

    public function test_stale_sku_split_identity_detaches_rather_than_violating_the_url_constraint(): void
    {

        $stale = $this->repo->upsert($this->shopId, 'https://testshop.test/wrong', 'X', [
            'sku' => 'SKU-2',
        ])->shopBook;
        $owner = $this->repo->upsert($this->shopId, 'https://testshop.test/right', 'Y')->shopBook;

        $result = $this->repo->upsert($this->shopId, 'https://testshop.test/right', 'Y', [
            'sku' => 'SKU-2',
        ]);

        self::assertSame($owner->id, $result->shopBook->id);
        self::assertSame('SKU-2', $result->shopBook->sku);
        self::assertNull(ShopBook::findOrFail($stale->id)->sku);
    }

    public function test_isbn_drift_unlinks_a_stale_canonical_match(): void
    {
        [$ownedIsbn, $otherIsbn] = [$this->uniqueIsbn(), $this->uniqueIsbn()];
        $bookId = DB::table('books')->insertGetId(
            ['title' => 'Canonical', 'data_source' => 'shop_inferred'],
            'id'
        );
        BookIsbn::create(['book_id' => $bookId, 'isbn' => $ownedIsbn, 'isbn_type' => 'isbn13']);

        $created = $this->repo->upsert($this->shopId, 'https://testshop.test/g', 'G', [
            'isbn' => $ownedIsbn,
        ])->shopBook;
        ShopBook::whereKey($created->id)->update(['book_id' => $bookId, 'match_status' => 'matched']);

        $result = $this->repo->upsert($this->shopId, 'https://testshop.test/g', 'G', [
            'isbn' => $otherIsbn,
        ]);

        self::assertNull($result->shopBook->book_id, 'stale link must be cleared');
        self::assertSame('unmatched', $result->shopBook->match_status);

        $fields = array_column($result->changes, 'field');
        self::assertContains('book_id', $fields);
        self::assertContains('match_status', $fields);
    }

    public function test_isbn_change_keeps_the_link_when_the_canonical_owns_both(): void
    {
        [$ownedIsbn, $otherIsbn] = [$this->uniqueIsbn(), $this->uniqueIsbn()];
        $bookId = DB::table('books')->insertGetId(
            ['title' => 'Canonical', 'data_source' => 'shop_inferred'],
            'id'
        );
        foreach ([$ownedIsbn, $otherIsbn] as $isbn) {
            BookIsbn::create(['book_id' => $bookId, 'isbn' => $isbn, 'isbn_type' => 'isbn13']);
        }

        $created = $this->repo->upsert($this->shopId, 'https://testshop.test/h', 'H', [
            'isbn' => $ownedIsbn,
        ])->shopBook;
        ShopBook::whereKey($created->id)->update(['book_id' => $bookId, 'match_status' => 'matched']);

        $result = $this->repo->upsert($this->shopId, 'https://testshop.test/h', 'H', [
            'isbn' => $otherIsbn,
        ]);

        self::assertSame($bookId, $result->shopBook->book_id);
    }

    public function test_multi_author_string_becomes_ordered_rows(): void
    {
        $book = $this->repo->upsert($this->shopId, 'https://testshop.test/i', 'I', [
            'author' => 'Jolanta Skridailė, Vilija Vyšniauskienė',
        ])->shopBook;

        $rows = DB::table('shop_book_authors')
            ->join('shop_authors', 'shop_authors.id', '=', 'shop_book_authors.author_id')
            ->where('shop_book_id', $book->id)
            ->orderBy('position')
            ->pluck('shop_authors.name')
            ->all();

        self::assertSame(['Jolanta Skridailė', 'Vilija Vyšniauskienė'], $rows);
    }

    public function test_repeated_author_name_yields_one_row(): void
    {
        $book = $this->repo->upsert($this->shopId, 'https://testshop.test/j', 'J', [
            'author' => 'Same Name and Same Name',
        ])->shopBook;

        self::assertSame(
            1,
            DB::table('shop_book_authors')->where('shop_book_id', $book->id)->count()
        );
    }

    public function test_author_list_shrinks_when_the_shop_drops_one(): void
    {
        $url = 'https://testshop.test/k';
        $book = $this->repo->upsert($this->shopId, $url, 'K', ['author' => 'A Author; B Author'])->shopBook;
        self::assertSame(2, DB::table('shop_book_authors')->where('shop_book_id', $book->id)->count());

        $this->repo->upsert($this->shopId, $url, 'K', ['author' => 'B Author']);

        $remaining = DB::table('shop_book_authors')
            ->join('shop_authors', 'shop_authors.id', '=', 'shop_book_authors.author_id')
            ->where('shop_book_id', $book->id)
            ->pluck('shop_authors.name')
            ->all();
        self::assertSame(['B Author'], $remaining);
    }

    #[DataProvider('authorStrings')]
    public function test_author_splitting(string $raw, array $expected): void
    {
        self::assertSame($expected, ShopBookRepository::splitAuthors($raw));
    }

    public static function authorStrings(): array
    {
        return [
            ['Solo Author', ['Solo Author']],
            ['A, B', ['A', 'B']],
            ['A; B', ['A', 'B']],
            ['A & B', ['A', 'B']],
            ['A / B', ['A', 'B']],
            ['A and B', ['A', 'B']],

            ['A ir B', ['A', 'B']],

            ['Tolkien,J.R.R.', ['Tolkien,J.R.R.']],
        ];
    }

    public function test_partial_properties_do_not_drop_earlier_attributes(): void
    {
        $url = 'https://testshop.test/l';
        $book = $this->repo->upsert($this->shopId, $url, 'L', [], [
            'pages' => 336,
            'cover_type' => 'Minkštas',
        ])->shopBook;

        $this->repo->upsert($this->shopId, $url, 'L', [], ['pages' => 340]);

        $attrs = ShopBookAttribute::where('shop_book_id', $book->id)
            ->pluck('value', 'key')
            ->all();

        self::assertSame('340', $attrs['pages']);
        self::assertSame('Minkštas', $attrs['cover_type'], 'earlier attribute must survive');
    }

    public function test_type_is_inferred_when_not_supplied(): void
    {
        $result = $this->repo->upsert($this->shopId, 'https://testshop.test/m', 'Some Novel', [
            'author' => 'An Author',
            'isbn' => '9786090901595',
            'format' => 'paperback',
        ]);

        self::assertSame('book', $result->shopBook->type);
    }

    public function test_toy_title_without_book_signals_is_not_a_book(): void
    {
        $result = $this->repo->upsert($this->shopId, 'https://testshop.test/n', 'Stalo žaidimas Kataną');

        self::assertSame('non_book', $result->shopBook->type);
    }

    private function uniqueIsbn(): string
    {
        static $counter = 0;

        $body = '978'.substr(str_pad((string) (getmypid() * 1000 + $counter++), 9, '0', STR_PAD_LEFT), -9);
        $total = 0;
        foreach (str_split($body) as $i => $digit) {
            $total += (int) $digit * ($i % 2 === 0 ? 1 : 3);
        }

        return $body.((10 - $total % 10) % 10);
    }
}
