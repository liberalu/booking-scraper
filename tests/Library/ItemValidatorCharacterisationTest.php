<?php

declare(strict_types=1);

namespace Tests\Library;

use App\Crawler\IssueBuffer;
use App\Crawler\ItemValidator;
use PHPUnit\Framework\TestCase;

/**
 * The validation layer, pinned to behaviour Python agreed with.
 *
 * `make validator-diff` proves this layer matches ValidationPipeline by
 * running both — which stops being possible the moment Python is deleted. So
 * the cases are frozen: `validator_diff.py --freeze` writes them out, and it
 * refuses to write unless every case matched first. What is asserted below is
 * therefore Python's behaviour captured, not merely PHP's own output blessed.
 *
 * The distinction matters when this test fails. It does not mean "PHP changed";
 * it means PHP no longer does what the reference implementation did, and the
 * reference is gone. Update the golden only with a reason.
 *
 * Needs no database, no network, and no Python.
 */
final class ItemValidatorCharacterisationTest extends TestCase
{
    /** @return list<array{label: string, url: string, item: array, attributes: array|null, expected: array}> */
    private static function cases(): array
    {
        $path = __DIR__ . '/golden/validator_cases.json';
        self::assertFileExists(
            $path,
            'run `make validator-diff FREEZE=1` while Python still exists'
        );

        return json_decode((string) file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
    }

    public function testEveryFrozenCaseStillBehavesTheSame(): void
    {
        foreach (self::cases() as $case) {
            IssueBuffer::reset();
            ['item' => $item, 'reject' => $reject] = ItemValidator::apply(
                $case['item'],
                $case['url'],
                $case['attributes'],
            );

            $actual = [
                // Nulls are dropped and scalars stringified, matching how the
                // differential normalised both sides before comparing.
                'item' => array_map(
                    static fn (mixed $v): mixed => is_scalar($v) && !is_string($v)
                        ? self::scalarToString($v)
                        : $v,
                    array_filter($item, static fn (mixed $v): bool => $v !== null),
                ),
                'reject' => $reject !== null,
                'issues' => self::sortedIssues(IssueBuffer::drain()),
            ];

            self::assertEquals(
                $case['expected'],
                $actual,
                "validation behaviour changed for: {$case['label']}"
            );
        }
    }

    /** A shrinking corpus would let this pass by asserting nothing. */
    public function testTheCorpusIsIntact(): void
    {
        $cases = self::cases();
        self::assertGreaterThanOrEqual(46, count($cases));

        $issues = array_merge(...array_map(
            static fn (array $c): array => $c['expected']['issues'],
            $cases
        ));
        self::assertGreaterThanOrEqual(
            30,
            count($issues),
            'the frozen cases must still exercise the checks, not just the happy path'
        );

        // Every check the layer can emit should appear somewhere, or the
        // golden has quietly stopped covering one.
        $kinds = array_unique(array_map(static fn (array $i): string => $i[0], $issues));
        foreach ([
            'missing_price', 'zero_price', 'price_higher_than_original',
            'invalid_price', 'invalid_price_original', 'missing_title',
            'suspicious_title', 'html_in_text', 'invalid_isbn', 'invalid_year',
            'year_pages_swap', 'format_mismatch', 'invalid_url',
            'attribute_unknown_key', 'attribute_invalid_value',
        ] as $expected) {
            self::assertContains($expected, $kinds, "no frozen case covers {$expected}");
        }
    }

    /** @param list<array{url: string, field: string, issue: string, raw_value: string|null}> $issues */
    private static function sortedIssues(array $issues): array
    {
        $rows = array_map(
            static fn (array $i): array
                => [$i['issue'], $i['field'], $i['url'], $i['raw_value']],
            $issues
        );
        usort($rows, static fn (array $a, array $b): int => [$a[0], $a[1], $a[2], $a[3] ?? '']
            <=> [$b[0], $b[1], $b[2], $b[3] ?? '']);

        return $rows;
    }

    private static function scalarToString(mixed $value): string
    {
        return is_bool($value) ? ($value ? 'True' : 'False') : (string) $value;
    }
}
