<?php

declare(strict_types=1);

namespace Tests\Unit;

use App\Services\ValidateService;
use App\Support\IssueMetadata;
use PHPUnit\Framework\TestCase;

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
