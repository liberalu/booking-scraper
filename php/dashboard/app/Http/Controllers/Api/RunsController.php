<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\Queries;
use App\Support\BookPresenter;
use App\Support\RunPresenter;
use BookScraper\Models\ScrapeRun;
use BookScraper\Models\ShopBook;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * GET /api/runs — list with filters + KPI header.
 *
 * Shape matches the Python endpoint; the SPA's run list and the shell's
 * "running now" badge both read it.
 */
final class RunsController
{
    private const WHEN_BOUNDS_HOURS = ['1h' => 1, '24h' => 24, '7d' => 168, '30d' => 720];

    /** Phase values the filter accepts verbatim. */
    private const EXACT_PHASES = ['scan', 'discover_sitemap', 'discover_categories', 'discover_full_crawl'];

    public function index(Request $request): array
    {
        $shop = (string) $request->query('shop', 'all');
        $phase = (string) $request->query('phase', 'all');
        $status = (string) $request->query('status', 'all');
        $when = (string) $request->query('when', 'any');
        $q = trim((string) $request->query('q', ''));
        $perPage = max(1, min((int) $request->query('per_page', 30), 200));
        $page = max(1, (int) $request->query('page', 1));

        $query = ScrapeRun::query()
            ->with('shop')
            ->join('shops', 'scrape_runs.shop_id', '=', 'shops.id')
            ->select('scrape_runs.*')
            ->orderByDesc('scrape_runs.started_at');

        if ($shop !== '' && $shop !== 'all') {
            $query->where('shops.name', $shop);
        }
        if ($phase !== '' && $phase !== 'all') {
            if ($phase === 'discover') {
                // There is no literal "discover" enum value — match variants.
                $query->where('scrape_runs.phase', 'like', 'discover\_%');
            } elseif (in_array($phase, self::EXACT_PHASES, true)) {
                $query->where('scrape_runs.phase', $phase);
            } else {
                // Unknown phase: match nothing rather than 500.
                $query->whereRaw('false');
            }
        }
        if ($status !== '' && $status !== 'all') {
            $query->where('scrape_runs.status', $status);
        }
        if (isset(self::WHEN_BOUNDS_HOURS[$when])) {
            $query->where(
                'scrape_runs.started_at',
                '>=',
                Carbon::now('UTC')->subHours(self::WHEN_BOUNDS_HOURS[$when])
            );
        }
        if ($q !== '') {
            $like = "%{$q}%";
            $query->where(function ($sub) use ($like, $q): void {
                $sub->where('shops.name', 'ilike', $like)
                    ->orWhereRaw('scrape_runs.phase::text ilike ?', [$like]);
                if (ctype_digit($q)) {
                    $sub->orWhere('scrape_runs.id', (int) $q);
                }
            });
        }

        $total = (clone $query)->count();
        $runs = $query->offset(($page - 1) * $perPage)->limit($perPage)->get();

        $runIds = $runs->pluck('id')->all();
        $terminal = Queries::runTerminalCounts($runIds);
        $viCounts = self::validationIssueCounts($runIds);
        $realCounts = self::realItemCounts($runIds);
        $rescrape = Queries::rescrapeFlags($runIds);

        $todayCutoff = Carbon::now('UTC')->subHours(24);

        return [
            'runs' => $runs->map(fn (ScrapeRun $run): array => RunPresenter::toArray(
                $run,
                terminalCount: $terminal[$run->id] ?? null,
                validationIssues: $viCounts[$run->id] ?? 0,
                itemsAdded: $realCounts[$run->id]['items_added'] ?? null,
                itemsUpdated: $realCounts[$run->id]['items_updated'] ?? null,
                rescrape: $rescrape[$run->id] ?? false,
            ))->all(),
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'pages' => Queries::pageCount($total, $perPage),
            'kpis' => [
                'running_now' => ScrapeRun::where('status', 'running')->count(),
                // 24h window so the KPI matches what the "24h" filter shows.
                'today_total' => ScrapeRun::where('started_at', '>=', $todayCutoff)->count(),
                'today_ok' => ScrapeRun::where('started_at', '>=', $todayCutoff)
                    ->where('status', 'completed')->count(),
                'today_failed' => ScrapeRun::where('started_at', '>=', $todayCutoff)
                    ->where('status', 'failed')->count(),
                'all_time' => ScrapeRun::count(),
            ],
        ];
    }

    /** @return array<int, int> */
    private static function validationIssueCounts(array $runIds): array
    {
        if ($runIds === []) {
            return [];
        }

        return DB::table('validation_issues')
            ->select('last_seen_run_id', DB::raw('count(id) as c'))
            ->whereIn('last_seen_run_id', $runIds)
            ->groupBy('last_seen_run_id')
            ->pluck('c', 'last_seen_run_id')
            ->map(fn ($v): int => (int) $v)
            ->all();
    }

    /**
     * Accurate counts from the records themselves rather than the run's own
     * counters, which can drift during a single-row restart handover:
     *   added   = shop_books created by the run
     *   updated = distinct shop_books the run changed
     *
     * @return array<int, array{items_added: int, items_updated: int}>
     */
    private static function realItemCounts(array $runIds): array
    {
        if ($runIds === []) {
            return [];
        }

        $added = DB::table('shop_books')
            ->select('created_run_id', DB::raw('count(id) as c'))
            ->whereIn('created_run_id', $runIds)
            ->groupBy('created_run_id')
            ->pluck('c', 'created_run_id')
            ->all();

        $updated = DB::table('shop_book_changes')
            ->select('scrape_run_id', DB::raw('count(distinct shop_book_id) as c'))
            ->whereIn('scrape_run_id', $runIds)
            ->groupBy('scrape_run_id')
            ->pluck('c', 'scrape_run_id')
            ->all();

        $out = [];
        foreach ($runIds as $id) {
            $out[$id] = [
                'items_added' => (int) ($added[$id] ?? 0),
                'items_updated' => (int) ($updated[$id] ?? 0),
            ];
        }

        return $out;
    }

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function show(int $runId): mixed
    {
        $run = ScrapeRun::with('shop')->find($runId);
        if ($run === null) {
            return response()->json(['detail' => 'Run not found'], 404);
        }

        $terminal = Queries::runTerminalCounts([$runId])[$runId] ?? null;
        $rescrape = Queries::rescrapeFlags([$runId])[$runId] ?? false;
        $counts = self::realItemCountsFor($runId);

        $base = RunPresenter::toArray($run, terminalCount: $terminal, rescrape: $rescrape);
        // The detail view uses record-derived counts, not the run's own
        // counters: those are spider-side batch tallies that never flush on a
        // reaped failure.
        $base['items_added'] = $counts['items_added'];
        $base['items_updated'] = $counts['items_updated'];
        $base['items'] = $counts['items_added'] + $counts['items_updated'];

        return [
            ...$base,
            'issues' => DB::table('validation_issues')
                ->select('field', 'issue')
                ->selectRaw('count(id) as count')
                ->where('last_seen_run_id', $runId)
                ->groupBy('field', 'issue')
                ->orderByDesc(DB::raw('count(id)'))
                ->get()
                ->map(fn (object $r): array => [
                    'field' => $r->field,
                    'issue' => $r->issue,
                    'count' => (int) $r->count,
                ])->all(),
            'close_reason' => self::closeReason($run),
            'pending_count' => DB::table('scrape_url_items')
                ->where('run_id', $runId)
                ->where('status', 'pending')
                ->count(),
            'events' => DB::table('scrape_run_events')
                ->where('run_id', $runId)
                ->orderBy('created_at')
                ->orderBy('id')
                ->get()
                ->map(fn (object $e): array => [
                    'id' => (int) $e->id,
                    'event_type' => $e->event_type,
                    'created_at' => RunPresenter::iso(
                        $e->created_at !== null ? Carbon::parse($e->created_at) : null
                    ),
                    'actor' => $e->actor,
                    'payload' => $e->payload !== null
                        ? json_decode((string) $e->payload, true)
                        : null,
                ])->all(),
        ];
    }

    /**
     * Why the run reached its current state. Null while non-terminal.
     *
     * A failed run's reason comes from its `scrape_run_failed` validation
     * issue (heartbeat_timeout, stall_timeout, orphan_on_boot, …), because
     * the close_reason column predates those and is not always populated.
     */
    private static function closeReason(ScrapeRun $run): ?string
    {
        if ($run->status === 'completed') {
            return $run->error_count > 0 ? 'completed_with_errors' : 'completed_ok';
        }
        if ($run->status !== 'failed') {
            return null;
        }

        $reason = DB::table('validation_issues')
            ->where('last_seen_run_id', $run->id)
            ->where('issue', 'scrape_run_failed')
            ->orderByDesc('id')
            ->value('raw_value');

        return ($reason !== null && $reason !== '') ? (string) $reason : 'failed';
    }

    /** @return array{items_added: int, items_updated: int} */
    private static function realItemCountsFor(int $runId): array
    {
        return self::realItemCounts([$runId])[$runId]
            ?? ['items_added' => 0, 'items_updated' => 0];
    }

    /**
     * GET /api/runs/{id}/books — what the run created or changed.
     *
     * `added` reads created_run_id, which is immutable and set once.
     * `updated` reads shop_book_changes, which is append-only and so
     * survives a crashed or reaped run.
     *
     * @return array<string, mixed>|\Illuminate\Http\JsonResponse
     */
    public function books(Request $request, int $runId): mixed
    {
        if (!ScrapeRun::whereKey($runId)->exists()) {
            return response()->json(['detail' => 'Run not found'], 404);
        }

        $type = (string) $request->query('type', 'added');
        if (!in_array($type, ['added', 'updated'], true)) {
            return response()->json(["detail" => "type must be 'added' or 'updated'"], 400);
        }

        $page = max(1, (int) $request->query('page', 1));
        $perPage = max(1, min((int) $request->query('per_page', 50), 100));

        if ($type === 'added') {
            // id breaks ties: titles repeat, and without a tiebreaker a book
            // can land on two pages while another never appears at all.
            $query = ShopBook::with('shop')->where('created_run_id', $runId)
                ->orderBy('title')->orderBy('id');
            $total = (clone $query)->count();
            $books = $query->offset(($page - 1) * $perPage)->limit($perPage)->get()
                ->map(fn (ShopBook $b): array => BookPresenter::toArray($b))
                ->all();
        } else {
            // string_agg of the distinct fields so the UI can show which
            // columns moved without a row-per-change payload.
            $changed = DB::table('shop_book_changes')
                ->select('shop_book_id')
                ->selectRaw("string_agg(distinct field, ', ') as changed_fields")
                ->where('scrape_run_id', $runId)
                ->groupBy('shop_book_id');

            $query = ShopBook::with('shop')
                ->joinSub($changed, 'c', 'c.shop_book_id', '=', 'shop_books.id')
                ->select('shop_books.*', 'c.changed_fields')
                ->orderBy('shop_books.title')->orderBy('shop_books.id');

            $total = DB::query()->fromSub($changed, 'c')->count();
            $books = $query->offset(($page - 1) * $perPage)->limit($perPage)->get()
                ->map(fn (ShopBook $b): array => [
                    ...BookPresenter::toArray($b),
                    'changed_fields' => $b->changed_fields,
                ])->all();
        }

        return [
            'books' => $books,
            'total' => $total,
            'page' => $page,
            'pages' => Queries::pageCount($total, $perPage),
        ];
    }
}
