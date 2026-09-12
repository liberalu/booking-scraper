<?php

declare(strict_types=1);

namespace Tests\Feature;

use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Group;
use Tests\Support\FixtureDatabase;
use Tests\TestCase;
use Tests\UsesTestDatabase;

/**
 * Every filter value a request accepts has to be one its column can hold.
 * These three used to pass validation and die on a PostgreSQL enum cast.
 */
final class QueryFilterValidationTest extends TestCase
{
    use UsesTestDatabase;

    protected function setUp(): void
    {
        parent::setUp();

        config(['dashboard.authentication_disabled' => true]);
        $this->useTestDatabase(FixtureDatabase::ensure(
            getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test',
            recreate: true
        ));
    }

    /** @return iterable<string, array{string}> */
    public static function accepted(): iterable
    {
        yield 'run status' => ['/api/runs?status=running'];
        yield 'shop book type' => ['/api/shop-books?type_filter=non_book'];
        yield 'trend all states' => ['/api/issues/trend?state=all'];
        yield 'trend open states' => ['/api/issues/trend?state=open'];
        yield 'trend one state' => ['/api/issues/trend?state=resolved'];
    }

    #[Group('db')]
    #[DataProvider('accepted')]
    public function test_valid_filters_are_served(string $path): void
    {
        $this->getJson($path)->assertOk();
    }

    /** @return iterable<string, array{string}> */
    public static function rejected(): iterable
    {
        yield 'url item status on the run list' => ['/api/runs?status=pending'];
        yield 'free text as a book type' => ['/api/shop-books?type_filter=whatever'];
    }

    #[Group('db')]
    #[DataProvider('rejected')]
    public function test_values_the_column_cannot_hold_are_rejected_before_the_query(string $path): void
    {
        $this->getJson($path)->assertUnprocessable();
    }

    #[Group('db')]
    public function test_url_item_statuses_still_filter_a_run_url_list(): void
    {
        $runId = DB::table('scrape_runs')->orderBy('id')->value('id');

        $this->getJson("/api/runs/{$runId}/urls?status=pending")->assertOk();
        $this->getJson("/api/runs/{$runId}/urls?status=running")->assertUnprocessable();
    }
}
