<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Casts\PostgresTextArray;
use App\Support\ValidationRules;
use DateTimeImmutable;
use Illuminate\Database\ConnectionInterface;
use Illuminate\Database\DatabaseManager;

final readonly class ValidationRepository
{
    private const int STALE_CADENCE_DAYS = 14;

    private StructuralValidationRepository $structural;

    public function __construct(
        private ValidationIssueRepository $writer,
        private DatabaseManager $database,
        ?StructuralValidationRepository $structural = null,
    ) {
        $this->structural = $structural ?? new StructuralValidationRepository($database);
    }

    /** @param list<array{issue: string, ...}> $issues */
    public function persist(array $issues, int $shopId, int $runId): void
    {
        $this->connection()->transaction(function () use ($issues, $shopId, $runId): void {
            $this->writer->upsert($issues, $shopId, $runId);
            $this->writer->resolveGone($shopId, $runId);
        });
    }

    private function liveBooks(string $alias = '', bool $inStock = false): string
    {
        $prefix = $alias !== '' ? "{$alias}." : '';
        $clauses = ["{$prefix}shop_id = ?", "{$prefix}is_active = true"];
        if ($inStock) {
            $clauses[] = "{$prefix}in_stock = true";
        }

        return implode(' AND ', $clauses);
    }

    /** @return list<array{issue: string, ...}> */
    public function checkStructuralDuplicates(int $shopId, int $runId): array
    {
        return $this->structural->duplicates($shopId, $runId);
    }

    /** @return list<array{issue: string, ...}> */
    public function checkSlugTitleMismatch(int $shopId, int $runId): array
    {
        return $this->structural->slugTitleMismatches($shopId, $runId);
    }

    /** @return list<array{issue: string, ...}> */
    public function checkSlugDiacriticLoss(int $shopId, int $runId): array
    {
        return $this->structural->slugDiacriticLosses($shopId, $runId);
    }

    /** @return list<array{issue: string, ...}> */
    public function checkDataCompleteness(int $shopId, int $runId): array
    {
        $results = [];

        foreach (['active_no_price', 'in_stock_no_price'] as $key) {
            foreach ($this->rows(
                'select id, url from shop_books
                 where '.$this->liveBooks('', true).' and price is null',
                [$shopId]
            ) as $row) {
                $results[] = $this->issue($runId, $row->string('url'), 'price', $key, null, $row->int('id'));
            }
        }

        foreach ($this->rows(
            'select id, url, title, categories from shop_books
             where '.$this->liveBooks()." and type = 'book'
               and isbn is null and author is null and year is null",
            [$shopId]
        ) as $row) {
            if ($this->looksNonBook($row)) {
                continue;
            }
            $results[] = $this->issue($runId, $row->string('url'), 'metadata', 'book_no_metadata', null, $row->int('id'));
        }

        foreach ($this->rows(
            'select sb.id, sb.url from shop_books sb
             left join prices p on p.shop_book_id = sb.id
             where '.$this->liveBooks('sb', true).' and p.id is null',
            [$shopId]
        ) as $row) {
            $results[] = $this->issue($runId, $row->string('url'), 'price_history', 'no_price_history', null, $row->int('id'));
        }

        return $results;
    }

    /** @return list<array{issue: string, ...}> */
    public function checkDataCorrectness(int $shopId, int $runId): array
    {
        $results = [];

        foreach ($this->rows(
            'select id, url, year from shop_books
             where '.$this->liveBooks().' and year is not null
               and (year < 1800 or year > extract(year from now())::int + 2)',
            [$shopId]
        ) as $row) {
            $results[] = $this->issue($runId, $row->string('url'), 'year', 'year_out_of_range', $row->string('year'), $row->int('id'));
        }

        foreach ($this->rows(
            'select id, url from shop_books
             where '.$this->liveBooks('', true).' and price = 0',
            [$shopId]
        ) as $row) {
            $results[] = $this->issue($runId, $row->string('url'), 'price', 'price_zero', '0', $row->int('id'));
        }

        foreach ($this->rows(
            'select id, url, format from shop_books
             where '.$this->liveBooks()." and format is not null
               and format ~ '^\\d+.*[xX×].*\\d+'",
            [$shopId]
        ) as $row) {
            $results[] = $this->issue($runId, $row->string('url'), 'format', 'format_is_dimensions', $row->nullableString('format'), $row->int('id'));
        }

        return $results;
    }

    /** @return list<array{issue: string, ...}> */
    public function checkClassificationConsistency(int $shopId, int $runId): array
    {
        $results = [];

        foreach ($this->rows(
            'select id, url, title, categories from shop_books
             where '.$this->liveBooks()." and type = 'book'
               and isbn is null and author is null
               and year is null and format is null",
            [$shopId]
        ) as $row) {
            if ($this->looksNonBook($row)) {
                continue;
            }
            $results[] = $this->issue($runId, $row->string('url'), 'type', 'book_no_signals', null, $row->int('id'));
        }

        foreach ($this->rows(
            'select id, url, isbn, title, categories from shop_books
             where '.$this->liveBooks()." and type = 'non_book'
               and isbn is not null and isbn ~ '^97[89]'",
            [$shopId]
        ) as $row) {
            if ($this->looksNonBook($row)) {
                continue;
            }
            $results[] = $this->issue($runId, $row->string('url'), 'type', 'non_book_has_isbn', $row->nullableString('isbn'), $row->int('id'));
        }

        $this->connection()->update(
            'update shop_books sb
             set is_active = false, inactive_since = now()
             where '.$this->liveBooks('sb')."
               and not exists (
                   select 1 from discovered_urls du
                   where du.shop_book_id = sb.id and du.url_type != 'non_product'
               )
               and exists (
                   select 1 from discovered_urls du
                   where du.shop_book_id = sb.id and du.url_type = 'non_product'
               )",
            [$shopId]
        );

        foreach ($this->rows(
            'select sb.id, sb.url from shop_books sb
             join discovered_urls du on du.shop_book_id = sb.id
             where '.$this->liveBooks('sb')." and du.url_type = 'non_product'",
            [$shopId]
        ) as $row) {
            $results[] = $this->issue($runId, $row->string('url'), 'url_type', 'non_product_active', 'non_product', $row->int('id'));
        }

        return $results;
    }

    /** @return list<array{issue: string, ...}> */
    public function checkStaleness(int $shopId, int $runId): array
    {
        $results = [];
        $days = 2 * self::STALE_CADENCE_DAYS;

        foreach ($this->rows(
            'select id, url, last_seen_at from shop_books
             where '.$this->liveBooks().'
               and last_seen_at < now() - make_interval(days => ?)',
            [$shopId, $days]
        ) as $row) {
            $results[] = $this->issue($runId, $row->string('url'), 'last_seen_at', 'stale_active', $this->isoTimestamp($row->nullableString('last_seen_at')), $row->int('id'));
        }

        foreach ($this->rows(
            'select sb.id, sb.url from shop_books sb
             join discovered_urls du on du.shop_book_id = sb.id
             where '.$this->liveBooks('sb')." and du.url_type = 'unreachable'",
            [$shopId]
        ) as $row) {
            $results[] = $this->issue($runId, $row->string('url'), 'url_type', 'unreachable_active', 'unreachable', $row->int('id'));
        }

        foreach ($this->rows(
            'select sb.id, sb.url from shop_books sb
             left join discovered_urls du on du.shop_book_id = sb.id
             where '.$this->liveBooks('sb').' and du.id is null',
            [$shopId]
        ) as $row) {
            $results[] = $this->issue($runId, $row->string('url'), 'url', 'orphan_no_url', $row->string('url'), $row->int('id'));
        }

        return $results;
    }

    /** @return list<array{issue: string, ...}> */
    public function checkMatchReadiness(int $shopId, int $runId): array
    {
        $results = [];

        foreach ($this->rows(
            'select id, url, isbn from shop_books
             where '.$this->liveBooks()." and match_status = 'unmatched'
               and isbn is not null",
            [$shopId]
        ) as $row) {
            $results[] = $this->issue($runId, $row->string('url'), 'match_status', 'unmatched_has_isbn', $row->nullableString('isbn'), $row->int('id'));
        }

        foreach ($this->rows(
            'select sb.id, sb.url, sb.isbn as sb_isbn,
                    (select bi2.isbn from book_isbns bi2 where bi2.book_id = b.id
                     order by bi2.isbn_type desc limit 1) as book_isbn
             from shop_books sb
             join books b on b.id = sb.book_id
             where '.$this->liveBooks('sb')." and sb.match_status = 'matched'
               and sb.isbn is not null
               and not exists (
                   select 1 from book_isbns bi
                   where bi.book_id = b.id
                     and (
                       bi.isbn = sb.isbn
                       or (length(bi.isbn) = 10 and length(sb.isbn) = 13
                           and substring(sb.isbn, 4, 9) = substring(bi.isbn, 1, 9))
                       or (length(sb.isbn) = 10 and length(bi.isbn) = 13
                           and substring(bi.isbn, 4, 9) = substring(sb.isbn, 1, 9))
                     )
               )",
            [$shopId]
        ) as $row) {
            $results[] = $this->issue($runId, $row->string('url'), 'isbn', 'match_isbn_drift', $row->string('sb_isbn').' vs '.$row->nullableString('book_isbn'), $row->int('id'));
        }

        return $results;
    }

    /** @return list<array{issue: string, ...}> */
    public function checkRelationshipIntegrity(int $shopId, int $runId): array
    {
        $candidates = $this->rows(
            'select sb.id, sb.url, du.url as alias_url
             from shop_books sb
             join discovered_urls du on du.shop_book_id = sb.id
             where '.$this->liveBooks('sb')."
               and rtrim(du.url, '/') != rtrim(sb.url, '/')
               and regexp_replace(rtrim(du.url, '/'), '^.+/', '')
                 != regexp_replace(rtrim(sb.url, '/'), '^.+/', '')",
            [$shopId]
        );

        $perBook = [];
        foreach ($candidates as $row) {
            if (! ValidationRules::isGenuineUrlAlias($row->string('url'), $row->string('alias_url'))) {
                continue;
            }
            $id = $row->int('id');
            if (isset($perBook[$id])) {
                $perBook[$id]['count']++;
            } else {
                $perBook[$id] = ['url' => $row->string('url'), 'count' => 1];
            }
        }

        $results = [];
        foreach ($perBook as $shopBookId => $found) {
            $results[] = $this->issue($runId, $found['url'], 'url', 'url_aliases', (string) $found['count'], $shopBookId);
        }

        return $results;
    }

    private function looksNonBook(DatabaseRow $row): bool
    {
        $categoriesRaw = $row->nullableString('categories');
        $categories = $categoriesRaw !== null
            ? PostgresTextArray::parse($categoriesRaw)
            : null;

        return ValidationRules::titleIndicatesNonBook($row->nullableString('title'))
            || ValidationRules::categoriesIndicateNonBook($categories);
    }

    /**
     * @return array{
     *     scrape_run_id: int,
     *     url: string,
     *     field: string,
     *     issue: string,
     *     raw_value: string|null,
     *     shop_book_id: int
     * }
     */
    private function issue(
        int $runId,
        string $url,
        string $field,
        string $issue,
        ?string $rawValue,
        int $shopBookId,
    ): array {
        return [
            'scrape_run_id' => $runId,
            'url' => $url,
            'field' => $field,
            'issue' => $issue,
            'raw_value' => $rawValue,
            'shop_book_id' => $shopBookId,
        ];
    }

    private function isoTimestamp(?string $value): ?string
    {
        if ($value === null) {
            return null;
        }
        $dt = new DateTimeImmutable($value);

        return $dt->format('u') === '000000'
            ? $dt->format('Y-m-d\TH:i:sP')
            : $dt->format('Y-m-d\TH:i:s.uP');
    }

    /**
     * @param  list<mixed>  $bindings
     * @return list<DatabaseRow>
     */
    private function rows(string $sql, array $bindings): array
    {
        return array_values(array_map(
            DatabaseRow::from(...),
            $this->connection()->select($sql, $bindings),
        ));
    }

    private function connection(): ConnectionInterface
    {
        return $this->database->connection();
    }
}
