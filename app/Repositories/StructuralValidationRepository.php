<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Support\ValidationRules;
use Illuminate\Database\ConnectionInterface;
use Illuminate\Database\DatabaseManager;

final readonly class StructuralValidationRepository
{
    public function __construct(private DatabaseManager $database) {}

    /** @return list<array{issue: string, ...}> */
    public function duplicates(int $shopId, int $runId): array
    {
        $results = [];
        foreach ($this->rows(
            'select sb.id, sb.url, sb.isbn from shop_books sb
             where '.self::liveBooks('sb')."
               and sb.isbn is not null and sb.isbn != ''
               and exists (
                   select 1 from shop_books sb2
                   where ".self::liveBooks('sb2').'
                     and sb2.isbn = sb.isbn and sb2.id != sb.id
               )',
            [$shopId, $shopId],
        ) as $row) {
            $results[] = self::issue($runId, $row->string('url'), 'isbn', 'isbn_duplicate', $row->nullableString('isbn'), $row->int('id'));
        }
        foreach ($this->rows(
            'select sb.id, sb.url, sb.title, sb.author from shop_books sb
             where '.self::liveBooks('sb').'
               and sb.title is not null and sb.author is not null
               and exists (
                   select 1 from shop_books sb2
                   where '.self::liveBooks('sb2').'
                     and lower(sb2.title) = lower(sb.title)
                     and lower(sb2.author) = lower(sb.author)
                     and sb2.id != sb.id
                     and (sb2.isbn = sb.isbn or (sb2.isbn is null and sb.isbn is null))
               )',
            [$shopId, $shopId],
        ) as $row) {
            $results[] = self::issue(
                $runId, $row->string('url'), 'title_author', 'title_author_duplicate',
                $row->string('title').' / '.$row->string('author'), $row->int('id'),
            );
        }

        return $results;
    }

    /** @return list<array{issue: string, ...}> */
    public function slugTitleMismatches(int $shopId, int $runId): array
    {
        $results = [];
        foreach ($this->titledBooks($shopId) as $row) {
            $slug = ValidationRules::slugFromUrl($row->string('url'));
            if (ValidationRules::shouldFlagSlugTitle($slug, $row->nullableString('title'))
                && ! ValidationRules::looksDiacriticLossy($slug, $row->nullableString('title'))) {
                $results[] = self::issue($runId, $row->string('url'), 'slug', 'slug_title_mismatch', $slug, $row->int('id'));
            }
        }

        return $results;
    }

    /** @return list<array{issue: string, ...}> */
    public function slugDiacriticLosses(int $shopId, int $runId): array
    {
        $results = [];
        foreach ($this->titledBooks($shopId) as $row) {
            $slug = ValidationRules::slugFromUrl($row->string('url'));
            if (! ValidationRules::looksDiacriticLossy($slug, $row->nullableString('title'))) {
                continue;
            }
            $issue = self::issue($runId, $row->string('url'), 'slug', 'slug_diacritic_loss', $slug, $row->int('id'));
            $issue['initial_state'] = 'acknowledged';
            $results[] = $issue;
        }

        return $results;
    }

    /** @return list<DatabaseRow> */
    private function titledBooks(int $shopId): array
    {
        return $this->rows('select id, url, title from shop_books where '.self::liveBooks().' and title is not null', [$shopId]);
    }

    private static function liveBooks(string $alias = ''): string
    {
        $prefix = $alias !== '' ? "{$alias}." : '';

        return "{$prefix}shop_id = ? AND {$prefix}is_active = true";
    }

    /** @return array{scrape_run_id: int, url: string, field: string, issue: string, raw_value: string|null, shop_book_id: int} */
    private static function issue(int $runId, string $url, string $field, string $issue, ?string $rawValue, int $shopBookId): array
    {
        return [
            'scrape_run_id' => $runId,
            'url' => $url,
            'field' => $field,
            'issue' => $issue,
            'raw_value' => $rawValue,
            'shop_book_id' => $shopBookId,
        ];
    }

    /**
     * @param  list<mixed>  $bindings
     * @return list<DatabaseRow>
     */
    private function rows(string $sql, array $bindings): array
    {
        return array_values(array_map(DatabaseRow::from(...), $this->connection()->select($sql, $bindings)));
    }

    private function connection(): ConnectionInterface
    {
        return $this->database->connection();
    }
}
