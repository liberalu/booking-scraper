<?php

declare(strict_types=1);

namespace App\Services;

use App\Repositories\ValidationRepository;
use RuntimeException;

final readonly class ValidateService
{
    public const array ISSUE_KEYS = [
        'active_no_price',
        'book_no_metadata',
        'book_no_signals',
        'format_is_dimensions',
        'in_stock_no_price',
        'isbn_duplicate',
        'match_isbn_drift',
        'no_price_history',
        'non_book_has_isbn',
        'non_product_active',
        'orphan_no_url',
        'price_zero',
        'slug_diacritic_loss',
        'slug_title_mismatch',
        'stale_active',
        'title_author_duplicate',
        'unmatched_has_isbn',
        'unreachable_active',
        'url_aliases',
        'year_out_of_range',
    ];

    public function __construct(private ValidationRepository $validation) {}

    /** @return array<string, int> */
    public function run(int $shopId, int $runId): array
    {
        $issues = [
            ...$this->validation->checkStructuralDuplicates($shopId, $runId),
            ...$this->validation->checkSlugTitleMismatch($shopId, $runId),
            ...$this->validation->checkSlugDiacriticLoss($shopId, $runId),
            ...$this->validation->checkDataCompleteness($shopId, $runId),
            ...$this->validation->checkDataCorrectness($shopId, $runId),
            ...$this->validation->checkClassificationConsistency($shopId, $runId),
            ...$this->validation->checkStaleness($shopId, $runId),
            ...$this->validation->checkMatchReadiness($shopId, $runId),
            ...$this->validation->checkRelationshipIntegrity($shopId, $runId),
        ];

        $counters = [];
        foreach ($issues as $issue) {
            $key = $issue['issue'];
            $counters[$key] = ($counters[$key] ?? 0) + 1;
        }

        $unknown = array_diff(array_keys($counters), self::ISSUE_KEYS);
        if ($unknown !== []) {
            throw new RuntimeException(
                'validator emitted unregistered issue key(s): '
                .implode(', ', $unknown)
                .' — add them to ISSUE_KEYS and to ISSUE_DESCRIPTIONS in the dashboard, '
                .'or fix the typo',
            );
        }

        $this->validation->persist($issues, $shopId, $runId);
        ksort($counters);

        return $counters;
    }
}
