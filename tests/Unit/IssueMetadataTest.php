<?php

declare(strict_types=1);

namespace Tests\Unit;

use App\Support\IssueMetadata;
use App\Services\ValidateService;
use PHPUnit\Framework\TestCase;

/**
 * Every issue the validator can emit must be one the dashboard can label.
 *
 * This replaces the guard that compared ValidateService::ISSUE_KEYS against
 * the Python validator's frozenset — the check that mattered was never
 * "do the two stacks agree" but "can the UI describe what the validator
 * writes". A key with no severity renders without its colour; a key with no
 * description renders a blank explanation on the issue page.
 *
 * The reverse direction is deliberately not asserted: IssueMetadata also
 * covers scrape-failure kinds (`scrape_run_failed`, `empty_response`,
 * `discover_fetch_failed`) that come from the crawler rather than the
 * validator, so it is a superset.
 */
final class IssueMetadataTest extends TestCase
{
    public function test_every_validator_issue_has_a_severity(): void
    {
        $missing = array_diff(ValidateService::ISSUE_KEYS, array_keys(IssueMetadata::SEVERITY));

        self::assertSame([], array_values($missing));
    }

    public function test_every_validator_issue_has_a_description(): void
    {
        $missing = array_diff(ValidateService::ISSUE_KEYS, array_keys(IssueMetadata::DESCRIPTIONS));

        self::assertSame([], array_values($missing));
    }

    public function test_every_severity_is_one_the_ui_styles(): void
    {
        foreach (IssueMetadata::SEVERITY as $issue => $severity) {
            self::assertContains(
                $severity,
                ['info', 'warning', 'critical'],
                "unknown severity for {$issue}"
            );
        }
    }
}
