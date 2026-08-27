<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\RunPresenter;
use App\Models\DiscoveredUrl;
use Illuminate\Support\Facades\DB;

/**
 * GET /api/urls/{id} — one discovered URL, with its classification and the
 * history of every scan that touched it.
 */
final class UrlDetailController
{
    /** fail_count at which a URL counts as failing. */
    private const FAILING_THRESHOLD = 3;

    /** How many past checks the history shows. */
    private const HISTORY_LIMIT = 20;

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function __invoke(int $urlId): mixed
    {
        $url = DiscoveredUrl::with(['shop', 'shopBook', 'classification'])->find($urlId);
        if ($url === null) {
            return response()->json(['detail' => 'URL not found'], 404);
        }

        $book = $url->shopBook;
        $classification = $url->classification;

        $detail = [
            'id' => $url->id,
            'url' => $url->url,
            'shop' => $url->shop->name ?? '—',
            'url_type' => $url->url_type ?: 'unknown',
            'source' => $url->source ?: '—',
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
                'reasons' => $classification->reasons !== null
                    ? json_decode((string) $classification->reasons, true)
                    : [],
            ];
        }

        $detail['last_http_status'] = $url->last_http_status;
        $detail['url_type'] = $url->url_type;
        $detail['last_checked_at'] = RunPresenter::iso($url->last_checked_at);
        $detail['last_checked_ago'] = RunPresenter::relative($url->last_checked_at);

        // Only terminal items: a pending or in-flight row is not a "check"
        // that happened yet.
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
            ->map(fn (object $row): array => [
                'run_id' => (int) $row->run_id,
                'when' => RunPresenter::relative(
                    $row->started_at !== null ? \Illuminate\Support\Carbon::parse($row->started_at) : null
                ),
                'started_at' => RunPresenter::iso(
                    $row->started_at !== null ? \Illuminate\Support\Carbon::parse($row->started_at) : null
                ),
                'http_status' => $row->http_status,
                // No status, or 4xx/5xx, both mean the check did not succeed.
                'status' => (!$row->http_status || $row->http_status >= 400) ? 'error' : 'ok',
                'done_at' => RunPresenter::iso(
                    $row->done_at !== null ? \Illuminate\Support\Carbon::parse($row->done_at) : null
                ),
            ])->all();

        return $detail;
    }
}
