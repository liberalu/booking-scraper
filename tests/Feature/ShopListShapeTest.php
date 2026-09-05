<?php

declare(strict_types=1);

namespace Tests\Feature;

use App\Repositories\OverviewReadRepository;
use App\Repositories\ShopReadRepository;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use Tests\Support\FixtureDatabase;
use Tests\TestCase;
use Tests\UsesTestDatabase;

/**
 * `sortBy()` preserves keys, so a shop list sorted into an order that differs
 * from insertion order serialises as a JSON object instead of an array — and
 * the dashboard's `shopCards.map is not a function`. SyntheticShop's shops
 * happen to be inserted in name order, so the API goldens cannot see this.
 */
final class ShopListShapeTest extends TestCase
{
    use UsesTestDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        $this->useTestDatabase(FixtureDatabase::ensure(
            getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test',
            recreate: true
        ));
    }

    #[Group('db')]
    public function test_shop_lists_stay_arrays_when_name_order_differs_from_id_order(): void
    {
        DB::beginTransaction();
        try {
            // Highest id, first alphabetically: sortBy has to move it to the front.
            DB::table('shops')->insert([
                'name' => 'aaa-sorts-first',
                'base_url' => 'https://aaa.example',
            ]);

            $this->assertTrue(
                array_is_list((new ShopReadRepository)->index()['shops']),
                '/api/shops shops must serialise as a JSON array',
            );
            $this->assertTrue(
                array_is_list((new OverviewReadRepository)()['shops']),
                '/api/overview shops must serialise as a JSON array',
            );
        } finally {
            DB::rollBack();
        }
    }
}
