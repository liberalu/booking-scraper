<?php

declare(strict_types=1);

namespace Tests\Unit;

use App\Runs\RunLaunchRequest;
use App\Runs\RunPhase;
use App\Support\CrawlSpawner;
use InvalidArgumentException;
use Tests\TestCase;

final class CrawlSpawnerTest extends TestCase
{
    private const PHP = '/runtime/php';

    private const DSN = 'postgresql://user:secret@db:5432/catalogue';

    public function test_scan_is_routed_to_crawl_with_scan_options(): void
    {
        self::assertSame([
            self::PHP,
            base_path('artisan'),
            'crawler:run',
            'scan',
            '--shop=vaga',
            '--mode=full',
            '--max-urls=0',
            '--cron-job-id=17',
            '--database='.self::DSN,
        ], $this->command(new RunLaunchRequest(
            phase: RunPhase::Scan,
            shop: 'vaga',
            mode: 'full',
            cronJobId: 17,
        )));
    }

    public function test_discover_is_routed_to_crawl(): void
    {
        self::assertSame([
            self::PHP,
            base_path('artisan'),
            'crawler:run',
            'discover',
            '--shop=pegasas',
            '--strategy=sitemap',
            '--database='.self::DSN,
        ], $this->command(new RunLaunchRequest(
            phase: RunPhase::Discover,
            shop: 'pegasas',
            strategy: 'sitemap',
        )));
    }

    public function test_match_and_validate_use_their_own_scripts(): void
    {
        self::assertSame([
            self::PHP,
            base_path('bin/match'),
            '--shop=vaga',
            '--database='.self::DSN,
        ], $this->command(new RunLaunchRequest(RunPhase::Match, 'vaga')));

        self::assertSame([
            self::PHP,
            base_path('bin/validate'),
            '--shop=vaga',
            '--database='.self::DSN,
        ], $this->command(new RunLaunchRequest(RunPhase::Validate, 'vaga')));
    }

    public function test_adoption_targets_one_run_and_does_not_rebuild_a_scan(): void
    {
        $command = $this->command(new RunLaunchRequest(
            phase: RunPhase::Scan,
            shop: 'vaga',
            adoptRunId: 42,
        ));

        self::assertContains('--adopt-run-id=42', $command);
        self::assertNotContains('--mode=full', $command);
        self::assertNotContains('--max-urls=0', $command);
    }

    public function test_non_scan_phase_cannot_adopt_a_queue(): void
    {
        $this->expectException(InvalidArgumentException::class);

        new RunLaunchRequest(RunPhase::Validate, 'vaga', adoptRunId: 42);
    }

    public function test_launch_request_rejects_conflicting_scan_inputs(): void
    {
        $this->expectException(InvalidArgumentException::class);

        new RunLaunchRequest(
            RunPhase::Scan,
            'vaga',
            mode: 'full',
            urls: 'https://example.test/book',
        );
    }

    private function command(RunLaunchRequest $request): array
    {
        return CrawlSpawner::buildCommand(
            $request,
            self::PHP,
            base_path('bin'),
            self::DSN,
        );
    }
}
