<?php

declare(strict_types=1);

namespace Tests\Repositories;

use App\DTO\Request\IssueQueryInput;
use App\DTO\Request\RunQueryInput;
use App\Models\ScrapeRun;
use App\Repositories\IssueReadRepository;
use App\Repositories\RunReadRepository;
use App\Repositories\StructuralValidationRepository;
use Illuminate\Database\DatabaseManager;
use Illuminate\Support\Facades\DB;
use PHPUnit\Framework\Attributes\Group;
use Tests\Support\FixtureDatabase;
use Tests\TestCase;
use Tests\UsesTestDatabase;

final class ReadRepositoryIntegrationTest extends TestCase
{
    use UsesTestDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        $this->useTestDatabase(FixtureDatabase::ensure(
            getenv('TEST_DATABASE_URL')
                ?: 'postgresql://postgres:postgres@localhost:5433/book_scraper_php_test',
            recreate: true,
        ));
    }

    #[Group('db')]
    public function test_read_repositories_preserve_their_database_contracts(): void
    {
        $runs = new RunReadRepository;
        $runList = $runs->index($this->runInput());
        self::assertArrayHasKey('runs', $runList);
        self::assertArrayHasKey('kpis', $runList);
        self::assertNotEmpty($runList['runs']);

        $runId = DB::table('scrape_runs')->orderBy('id')->value('id');
        self::assertIsNumeric($runId);
        $run = ScrapeRun::findOrFail((int) $runId);
        $runDetail = $runs->show($run);
        self::assertSame($run->id, $runDetail['id']);
        self::assertArrayHasKey('events', $runDetail);
        self::assertArrayHasKey('issues', $runDetail);

        $issues = (new IssueReadRepository)->index($this->issueInput());
        self::assertArrayHasKey('issues', $issues);
        self::assertArrayHasKey('counts', $issues);
        self::assertSame('all', $issues['kind']);
        self::assertGreaterThan(0, $issues['total']);

        $shopId = DB::table('shops')->where('name', 'synthetic')->value('id');
        self::assertIsNumeric($shopId);
        $database = $this->app->make(DatabaseManager::class);
        $structural = new StructuralValidationRepository($database);
        self::assertIsArray($structural->duplicates((int) $shopId, $run->id));
        self::assertIsArray($structural->slugTitleMismatches((int) $shopId, $run->id));
        self::assertIsArray($structural->slugDiacriticLosses((int) $shopId, $run->id));
    }

    private function runInput(): RunQueryInput
    {
        return new RunQueryInput(
            shop: 'all',
            phase: 'all',
            status: 'all',
            when: 'any',
            search: '',
            page: 1,
            perPage: 20,
            type: null,
            sort: null,
            order: null,
            errorReason: '',
            errorReasonIsNull: false,
            httpStatus: null,
            httpStatusIsNull: false,
            includeAcknowledged: false,
            note: '',
        );
    }

    private function issueInput(): IssueQueryInput
    {
        return new IssueQueryInput(
            state: 'new',
            shop: 'all',
            issueType: '',
            runId: null,
            severity: '',
            urlType: null,
            bookType: null,
            search: '',
            sortBy: 'age',
            order: 'desc',
            page: 1,
            perPage: 30,
            kind: 'all',
            groupBy: null,
            days: null,
        );
    }
}
