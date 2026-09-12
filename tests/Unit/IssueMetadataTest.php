<?php

declare(strict_types=1);

namespace Tests\Unit;

use App\Services\ValidateService;
use App\Support\IssueMetadata;
use PHPUnit\Framework\TestCase;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;
use SplFileInfo;

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

    public function test_every_issue_the_crawler_emits_is_registered(): void
    {
        $emitted = [];
        foreach ($this->sourceFiles() as $file) {
            preg_match_all("/->add\\(\\s*'([a-z0-9_]+)'/", (string) file_get_contents($file), $matches);
            foreach ($matches[1] as $key) {
                $emitted[$key] = $file;
            }
        }

        self::assertNotEmpty($emitted, 'the source scan found no issue emitters at all');
        foreach ($emitted as $key => $file) {
            self::assertArrayHasKey($key, IssueMetadata::SEVERITY, "{$key} is emitted by {$file} but has no severity");
            self::assertArrayHasKey($key, IssueMetadata::DESCRIPTIONS, "{$key} is emitted by {$file} but has no description");
        }
    }

    /** @return list<string> */
    private function sourceFiles(): array
    {
        $root = dirname(__DIR__, 2);
        $files = glob($root.'/bin/*') ?: [];
        $iterator = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root.'/app'));
        foreach ($iterator as $file) {
            if ($file instanceof SplFileInfo && $file->getExtension() === 'php') {
                $files[] = $file->getPathname();
            }
        }

        return array_values(array_filter($files, is_file(...)));
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
