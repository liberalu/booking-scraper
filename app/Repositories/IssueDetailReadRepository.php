<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ValidationIssue;
use App\Support\IssueMetadata;
use App\Support\RunPresenter;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use LogicException;

final class IssueDetailReadRepository
{
    private const string KIND_VALIDATION = 'validation';

    /** @return array<string, mixed> */
    public function show(ValidationIssue $issue): array
    {
        $issueId = $issue->id;
        $rawRow = DB::table('validation_issues as vi')
            ->join('scrape_runs as sr', 'sr.id', '=', 'vi.last_seen_run_id')
            ->leftJoin('shop_books as sb', 'sb.id', '=', 'vi.shop_book_id')
            ->leftJoin('shops as s', 's.id', '=', 'sr.shop_id')
            ->select(
                'vi.*',
                'sr.shop_id as run_shop_id',
                'sr.started_at as run_started_at',
                'sb.id as sb_id',
                'sb.title as sb_title',
                'sb.isbn as sb_isbn',
                'sb.book_id as sb_book_id',
                's.name as shop_name',
            )
            ->where('vi.id', $issueId)
            ->first();

        if ($rawRow === null) {
            throw new LogicException('Bound validation issue is no longer available.');
        }
        $row = DatabaseRow::from($rawRow);

        $discoveredUrlId = $row->nullableInt('discovered_url_id');
        $discovered = null;
        if ($discoveredUrlId === null && $row->string('url') !== '') {
            $discovered = DatabaseRow::nullable(DB::table('discovered_urls')
                ->where('url', $row->string('url'))
                ->where('shop_id', $row->int('run_shop_id'))
                ->first());
            $discoveredUrlId = $discovered?->nullableInt('id');
        }

        $shopBook = $row->nullableInt('sb_id') !== null ? $row : null;
        if ($shopBook === null) {
            $viaUrl = $discovered?->nullableInt('shop_book_id')
                ?? ($discoveredUrlId !== null
                    ? DatabaseRow::from([
                        'id' => DB::table('discovered_urls')->where('id', $discoveredUrlId)->value('shop_book_id'),
                    ])->nullableInt('id')
                    : null);
            if ($viaUrl !== null) {
                $book = DB::table('shop_books')->where('id', $viaUrl)->first();
                if ($book !== null) {
                    $bookRow = DatabaseRow::from($book);
                    $shopBook = DatabaseRow::from([
                        'sb_id' => $bookRow->int('id'),
                        'sb_title' => $bookRow->nullableString('title'),
                        'sb_isbn' => $bookRow->nullableString('isbn'),
                        'sb_book_id' => $bookRow->nullableInt('book_id'),
                    ]);
                }
            }
        }

        $issueType = $row->string('issue');
        $runStartedAt = $row->nullableString('run_started_at');

        return [
            'id' => $row->int('id'),
            'kind' => self::KIND_VALIDATION,
            'url' => $row->string('url'),
            'field' => $row->string('field'),
            'issue' => $issueType,
            'raw_value' => $row->nullableString('raw_value'),
            'scrape_run_id' => $row->int('last_seen_run_id'),
            'shop_book_id' => $row->nullableInt('shop_book_id') ?? $shopBook?->nullableInt('sb_id'),
            'discovered_url_id' => $discoveredUrlId,
            'shop_book_title' => $shopBook?->nullableString('sb_title'),
            'shop_name' => $row->nullableString('shop_name'),
            'lifecycle_state' => $row->string('lifecycle_state'),
            'acknowledged_at' => $this->iso($row->nullableString('acknowledged_at')),
            'severity' => IssueMetadata::severity($issueType),
            'added_at' => $this->iso($runStartedAt),
            'added_ago' => RunPresenter::relative(
                $runStartedAt === null ? null : Carbon::parse($runStartedAt)
            ),
            'description' => IssueMetadata::description($issueType),
            'match_context' => $this->matchContext($row, $shopBook),
        ];
    }

    /** @return array<string, mixed>|null */
    private function matchContext(DatabaseRow $row, ?DatabaseRow $shopBook): ?array
    {
        if ($row->string('issue') !== 'match_isbn_drift' || $shopBook === null
            || $shopBook->nullableInt('sb_book_id') === null) {
            return null;
        }

        $bookId = $shopBook->int('sb_book_id');
        $canonical = DatabaseRow::nullable(DB::table('books')->where('id', $bookId)->first());
        $isbnValues = DB::table('book_isbns')
            ->where('book_id', $bookId)
            ->orderByDesc('isbn_type')
            ->pluck('isbn')
            ->all();
        $isbns = array_values(array_filter($isbnValues, is_string(...)));

        $parts = explode(' vs ', $row->nullableString('raw_value') ?? '', 2);
        $shopIsbn = trim($parts[0]);
        $bookIsbn = trim($parts[1] ?? '');

        return [
            'sb_isbn' => $shopIsbn === '' ? $shopBook->nullableString('sb_isbn') : $shopIsbn,
            'book_isbn' => $bookIsbn === '' ? null : $bookIsbn,
            'book_id' => $bookId,
            'book_title' => $canonical?->nullableString('title'),
            'book_isbns' => $isbns,
        ];
    }

    private function iso(?string $timestamp): ?string
    {
        if ($timestamp === null) {
            return null;
        }
        $dt = Carbon::parse($timestamp)->utc();

        return $dt->micro === 0
            ? $dt->format('Y-m-d\TH:i:sP')
            : $dt->format('Y-m-d\TH:i:s.uP');
    }
}
