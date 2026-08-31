<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\DiscoveredUrl;
use App\Support\RunPresenter;
use Illuminate\Support\Facades\DB;

final class UrlDetailReadRepository
{
    private const int FAILING_THRESHOLD = 3;

    private const int HISTORY_LIMIT = 20;

    /** @return array<string, mixed> */
    public function __invoke(DiscoveredUrl $url): array
    {
        $url->load(['shop', 'shopBook', 'classification']);
        $urlId = $url->id;

        $book = $url->shopBook;
        $classification = $url->classification;

        $detail = [
            'id' => $url->id,
            'url' => $url->url,
            'shop' => $url->shop->name ?? '—',
            'url_type' => $url->url_type !== '' ? $url->url_type : 'unknown',
            'source' => $url->source !== null && $url->source !== '' ? $url->source : '—',
            'fail_count' => $url->fail_count,
            'status' => $url->fail_count >= self::FAILING_THRESHOLD ? 'error' : 'ok',
            'first_seen_at' => RunPresenter::iso($url->first_seen_at),
            'last_seen_ago' => RunPresenter::relative($url->last_seen_at),
            'last_scraped_ago' => RunPresenter::relative($url->last_seen_at),
            'discovered_ago' => RunPresenter::relative($url->first_seen_at),
            'book_title' => $book->title ?? '—',
            'book_id' => $book->id ?? null,
            'book_score' => $classification->book_score ?? null,
            'is_book' => $classification->is_book_product ?? null,
        ];

        if ($classification !== null) {
            $detail['classification'] = [
                'book_score' => $classification->book_score,
                'is_book_product' => $classification->is_book_product,
                'reasons' => $classification->reasons,
            ];
        }

        $detail['last_http_status'] = $url->last_http_status;
        $detail['url_type'] = $url->url_type;
        $detail['last_checked_at'] = RunPresenter::iso($url->last_checked_at);
        $detail['last_checked_ago'] = RunPresenter::relative($url->last_checked_at);

        $detail['check_history'] = DB::table('scrape_url_items')
            ->join('scrape_runs', 'scrape_runs.id', '=', 'scrape_url_items.run_id')
            ->select(
                'scrape_url_items.run_id',
                'scrape_url_items.http_status',
                'scrape_url_items.done_at',
                'scrape_runs.started_at',
            )
            ->where('scrape_url_items.discovered_url_id', $urlId)
            ->whereIn('scrape_url_items.status', ['done', 'failed'])
            ->orderByDesc('scrape_runs.started_at')
            ->limit(self::HISTORY_LIMIT)
            ->get()
            ->map(function (mixed $result): array {
                $row = DatabaseRow::from($result);
                $startedAt = $row->value('started_at') !== null ? $row->dateTime('started_at') : null;
                $doneAt = $row->value('done_at') !== null ? $row->dateTime('done_at') : null;
                $httpStatus = $row->nullableInt('http_status');

                return [
                    'run_id' => $row->int('run_id'),
                    'when' => RunPresenter::relative($startedAt),
                    'started_at' => RunPresenter::iso($startedAt),
                    'http_status' => $httpStatus,
                    'status' => ($httpStatus === null || $httpStatus >= 400) ? 'error' : 'ok',
                    'done_at' => RunPresenter::iso($doneAt),
                ];
            })->all();

        return $detail;
    }
}
