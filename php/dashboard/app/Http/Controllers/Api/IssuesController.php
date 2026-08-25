<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\Queries;
use App\Support\IssueMetadata;
use App\Support\RunPresenter;
use BookScraper\Models\Shop;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * GET /api/issues — the triage inbox.
 *
 * Spans two sources: `validation_issues` (parser-level data quality) and
 * `scrape_failures` (transport/HTTP events). Each row carries a `kind` so
 * the frontend can route them differently; `error_reason` and `http_status`
 * are null on validation rows and populated on failure rows.
 */
final class IssuesController
{
    private const KIND_VALIDATION = 'validation';
    private const KIND_SCRAPE_FAILURE = 'scrape_failure';

    private const LIFECYCLE_STATES = ['new', 'acknowledged', 'snoozed', 'resolved'];

    private const SORTABLE = ['age', 'id', 'type', 'shop', 'book', 'sev'];

    /** Prefix => severity for scrape failures, keyed on the part before ':'. */
    private const FAILURE_SEVERITY = [
        'request_error' => 'critical',
        'anti_bot_detected' => 'critical',
        'schema_drift' => 'critical',
        'rate_limited' => 'warning',
        'robots_disallowed' => 'warning',
        'soft_404' => 'warning',
    ];

    public function index(Request $request): array
    {
        $state = (string) $request->query('state', 'new');
        $shopName = (string) $request->query('shop', '');
        $issueType = (string) $request->query('issue_type', '');
        $runId = (int) $request->query('run_id', 0) ?: null;
        $severity = (string) $request->query('severity', '');
        $urlType = self::filterValue($request->query('url_type'));
        $bookType = self::filterValue($request->query('book_type'));
        $search = (string) $request->query('q', '');
        $sortBy = in_array($request->query('sort_by'), self::SORTABLE, true)
            ? (string) $request->query('sort_by')
            : 'age';
        $order = $request->query('order') === 'asc' ? 'asc' : 'desc';
        $page = max(1, (int) $request->query('page', 1));
        $perPage = max(1, min((int) $request->query('per_page', 30), 200));

        $kind = (string) $request->query('kind', 'all');
        if (!in_array($kind, ['all', self::KIND_VALIDATION, self::KIND_SCRAPE_FAILURE], true)) {
            $kind = 'all';
        }

        $shopId = null;
        if ($shopName !== '' && $shopName !== 'all') {
            $shopId = Shop::where('name', $shopName)->value('id') ?? -1;
        }

        // For the merged view, take up to page*per_page from each source then
        // merge and slice. The pigeonhole holds: the Nth-newest merged row
        // must appear in the top N*per_page of at least one source.
        $helperPage = $kind === 'all' ? 1 : $page;
        $helperPerPage = $kind === 'all' ? $page * $perPage : $perPage;

        $rows = [];
        $total = 0;

        if ($kind === 'all' || $kind === self::KIND_VALIDATION) {
            [$vRows, $vTotal] = $this->validationIssues(
                $state, $shopId, $issueType, $runId, $search, $severity,
                $urlType, $bookType, $order, $sortBy, $helperPage, $helperPerPage
            );
            $rows = [...$rows, ...$vRows];
            $total += $vTotal;
        }

        if ($kind === 'all' || $kind === self::KIND_SCRAPE_FAILURE) {
            [$fRows, $fTotal] = $this->scrapeFailures(
                $state, $shopId, $issueType, $runId, $search, $severity,
                $order, $sortBy, $helperPage, $helperPerPage
            );
            $rows = [...$rows, ...$fRows];
            $total += $fTotal;
        }

        if ($kind === 'all') {
            $rows = self::mergeSort($rows, $sortBy, $order);
            $rows = array_slice($rows, ($page - 1) * $perPage, $perPage);
        }

        return [
            'issues' => array_map([self::class, 'present'], $rows),
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'pages' => Queries::pageCount($total, $perPage),
            'counts' => $this->lifecycleCounts($shopId, $issueType, $runId, $search, $severity),
            'kind' => $kind,
        ];
    }

    // ------------------------------------------------------ validation rows

    /** @return array{0: list<array<string, mixed>>, 1: int} */
    private function validationIssues(
        string $state,
        ?int $shopId,
        string $issueType,
        ?int $runId,
        string $search,
        string $severity,
        ?string $urlType,
        ?string $bookType,
        string $order,
        string $sortBy,
        int $page,
        int $perPage,
    ): array {
        $query = DB::table('validation_issues as vi')
            ->join('scrape_runs as sr', 'sr.id', '=', 'vi.last_seen_run_id')
            ->leftJoin('shop_books as sb', 'sb.id', '=', 'vi.shop_book_id')
            // Joined on (url, shop) rather than the FK: an issue may predate
            // the shop_book link, and url_type still needs to be shown.
            ->leftJoin('discovered_urls as du', function ($join): void {
                $join->on('du.url', '=', 'vi.url')->on('du.shop_id', '=', 'sr.shop_id');
            })
            ->leftJoin('shops as s', 's.id', '=', 'sr.shop_id');

        if (in_array($state, self::LIFECYCLE_STATES, true)) {
            $query->where('vi.lifecycle_state', $state);
        } elseif ($state === 'open') {
            // Legacy alias kept so old dashboard links still work.
            $query->where('vi.lifecycle_state', 'new');
        }

        if ($shopId !== null) {
            $query->where('sr.shop_id', $shopId);
        }
        if ($issueType !== '') {
            $query->where('vi.issue', $issueType);
        }
        if (in_array($severity, ['critical', 'warning'], true)) {
            $query->whereIn('vi.issue', IssueMetadata::typesWithSeverity($severity));
        }
        if ($runId !== null) {
            $query->where('vi.last_seen_run_id', $runId);
        }
        if ($urlType !== null) {
            $query->where('du.url_type', $urlType);
        }
        if ($bookType !== null) {
            $query->where('sb.type', $bookType);
        }
        if ($search !== '') {
            $like = "%{$search}%";
            $query->where(fn ($q) => $q->where('vi.url', 'ilike', $like)
                ->orWhere('sb.title', 'ilike', $like));
        }

        $total = (clone $query)->count();

        // Every sort gets an id tiebreaker so pagination is stable.
        $tie = "vi.id {$order}";
        match ($sortBy) {
            'id' => $query->orderByRaw("vi.id {$order}"),
            'type' => $query->orderByRaw("vi.issue {$order}, {$tie}"),
            'shop' => $query->orderByRaw("s.name {$order} nulls last, {$tie}"),
            'book' => $query->orderByRaw("sb.title {$order} nulls last, {$tie}"),
            'sev' => $query->orderByRaw(
                '(case when vi.issue in (' . self::placeholders(IssueMetadata::typesWithSeverity('critical'))
                . ") then 1 else 2 end) {$order}, {$tie}",
                IssueMetadata::typesWithSeverity('critical')
            ),
            default => $query->orderByRaw("sr.started_at {$order} nulls last, {$tie}"),
        };

        $rows = $query
            ->select(
                'vi.*',
                'sr.shop_id as run_shop_id',
                'sr.started_at as run_started_at',
                'sb.title as shop_book_title',
                'sb.type as book_type',
                'du.url_type as du_url_type',
                's.name as shop_name',
            )
            ->offset(($page - 1) * $perPage)
            ->limit($perPage)
            ->get();

        return [
            $rows->map(fn (object $r): array => [
                'id' => (int) $r->id,
                'kind' => self::KIND_VALIDATION,
                'url' => $r->url,
                'field' => $r->field,
                'issue' => $r->issue,
                'raw_value' => $r->raw_value,
                'error_reason' => null,
                'http_status' => null,
                // Alias for frontend code that predates the rename.
                'scrape_run_id' => $r->last_seen_run_id,
                'last_seen_run_id' => $r->last_seen_run_id,
                'first_seen_run_id' => $r->first_seen_run_id,
                'run_count' => $r->run_count,
                'resolved_at' => self::iso($r->resolved_at),
                'snoozed_until' => self::iso($r->snoozed_until),
                'shop_book_id' => $r->shop_book_id,
                'shop_book_title' => $r->shop_book_title,
                'shop_id' => $r->run_shop_id,
                'shop_name' => $r->shop_name,
                'url_type' => $r->du_url_type,
                'book_type' => $r->book_type,
                'lifecycle_state' => $r->lifecycle_state,
                'added_at' => $r->run_started_at,
                'severity' => IssueMetadata::severity((string) $r->issue),
            ])->all(),
            $total,
        ];
    }

    // -------------------------------------------------------- failure rows

    /** @return array{0: list<array<string, mixed>>, 1: int} */
    private function scrapeFailures(
        string $state,
        ?int $shopId,
        string $issueType,
        ?int $runId,
        string $search,
        string $severity,
        string $order,
        string $sortBy,
        int $page,
        int $perPage,
    ): array {
        $query = DB::table('scrape_failures as sf')
            ->leftJoin('shop_books as sb', function ($join): void {
                $join->on('sb.shop_id', '=', 'sf.shop_id')->on('sb.url', '=', 'sf.url');
            })
            ->leftJoin('shops as s', 's.id', '=', 'sf.shop_id');

        if (in_array($state, self::LIFECYCLE_STATES, true)) {
            $query->where('sf.lifecycle_state', $state);
        } elseif ($state === 'open') {
            // Failures use a different 'open' definition than validation
            // issues: anything not yet acknowledged.
            $query->where('sf.lifecycle_state', '!=', 'acknowledged');
        }

        if ($shopId !== null) {
            $query->where('sf.shop_id', $shopId);
        }
        if ($runId !== null) {
            $query->where('sf.run_id', $runId);
        }
        if ($issueType !== '') {
            // issue_type doubles as the error_reason filter for this source.
            $query->where('sf.error_reason', $issueType);
        }
        if ($search !== '') {
            $like = "%{$search}%";
            $query->where(fn ($q) => $q->where('sf.url', 'ilike', $like)
                ->orWhere('sb.title', 'ilike', $like));
        }
        if (in_array($severity, ['critical', 'warning'], true)) {
            $this->applyFailureSeverity($query, $severity);
        }

        $total = (clone $query)->count();

        $tie = "sf.id {$order}";
        match ($sortBy) {
            'id' => $query->orderByRaw("sf.id {$order}"),
            'type' => $query->orderByRaw("sf.error_reason {$order} nulls last, {$tie}"),
            'shop' => $query->orderByRaw("s.name {$order} nulls last, {$tie}"),
            'book' => $query->orderByRaw("sb.title {$order} nulls last, {$tie}"),
            // 'sev' has no clean SQL expression for failures (the http range
            // wins over the prefix), so it falls back to age.
            default => $query->orderByRaw("sf.occurred_at {$order}, {$tie}"),
        };

        $rows = $query
            ->select('sf.*', 'sb.id as sb_id', 'sb.title as sb_title', 's.name as shop_name')
            ->offset(($page - 1) * $perPage)
            ->limit($perPage)
            ->get();

        return [
            $rows->map(fn (object $r): array => [
                'id' => (int) $r->id,
                'kind' => self::KIND_SCRAPE_FAILURE,
                'url' => $r->url,
                'field' => 'response',
                'issue' => $r->error_reason ?: 'unknown',
                'raw_value' => $r->http_status !== null ? (string) $r->http_status : null,
                'error_reason' => $r->error_reason,
                'http_status' => $r->http_status,
                'scrape_run_id' => $r->run_id,
                'shop_book_id' => $r->sb_id !== null ? (int) $r->sb_id : null,
                'shop_book_title' => $r->sb_title,
                'shop_id' => $r->shop_id,
                'shop_name' => $r->shop_name,
                'lifecycle_state' => $r->lifecycle_state,
                'added_at' => $r->occurred_at,
                'severity' => self::failureSeverity($r->error_reason, $r->http_status),
            ])->all(),
            $total,
        ];
    }

    /**
     * Mirror severityForFailure() in SQL. The http_status range wins when
     * set, so per-status reasons (`http_503`) resolve through the bucket
     * without the data needing a backfill.
     */
    private function applyFailureSeverity(mixed $query, string $severity): void
    {
        $critical = array_keys(array_filter(
            self::FAILURE_SEVERITY,
            static fn (string $v): bool => $v === 'critical'
        ));
        $warning = array_keys(array_filter(
            self::FAILURE_SEVERITY,
            static fn (string $v): bool => $v === 'warning'
        ));

        if ($severity === 'critical') {
            // Critical means a critical prefix AND no http range verdict.
            $query->where(function ($outer) use ($critical): void {
                $outer->where(function ($q) use ($critical): void {
                    foreach ($critical as $prefix) {
                        $q->orWhere('sf.error_reason', 'like', "{$prefix}%");
                    }
                })->where(function ($q): void {
                    $q->whereNull('sf.http_status')
                        ->orWhere('sf.http_status', '<', 400)
                        ->orWhere('sf.http_status', '>=', 600);
                });
            });

            return;
        }

        $query->where(function ($q) use ($warning): void {
            $q->where(function ($inner): void {
                $inner->whereNotNull('sf.http_status')
                    ->where('sf.http_status', '>=', 400)
                    ->where('sf.http_status', '<', 600);
            });
            foreach ($warning as $prefix) {
                $q->orWhere('sf.error_reason', 'like', "{$prefix}%");
            }
        });
    }

    /** Unknown reasons default to warning; the operator can still triage. */
    private static function failureSeverity(?string $errorReason, ?int $httpStatus): string
    {
        if ($httpStatus !== null && $httpStatus >= 400 && $httpStatus < 600) {
            return 'warning';
        }
        if ($errorReason !== null && $errorReason !== '') {
            $prefix = explode(':', $errorReason, 2)[0];

            return self::FAILURE_SEVERITY[$prefix] ?? 'warning';
        }

        return 'warning';
    }

    // ------------------------------------------------------------- merging

    /**
     * Sort the merged set in PHP: the two sources cannot be ordered by one
     * SQL statement.
     *
     * @param  list<array<string, mixed>>  $rows
     * @return list<array<string, mixed>>
     */
    private static function mergeSort(array $rows, string $sortBy, string $order): array
    {
        $severityRank = ['critical' => 1, 'warning' => 2];

        $key = static function (array $row) use ($sortBy, $severityRank): mixed {
            return match ($sortBy) {
                'id' => $row['id'] ?? 0,
                'type' => mb_strtolower((string) ($row['issue'] ?? $row['error_reason'] ?? ''), 'UTF-8'),
                'shop' => mb_strtolower((string) ($row['shop_name'] ?? ''), 'UTF-8'),
                'book' => mb_strtolower((string) ($row['shop_book_title'] ?? ''), 'UTF-8'),
                'sev' => $severityRank[$row['severity'] ?? 'warning'] ?? 2,
                // Absent timestamps sort oldest, matching datetime.min.
                default => (string) ($row['added_at'] ?? '0001-01-01 00:00:00'),
            };
        };

        usort($rows, static function (array $a, array $b) use ($key, $order): int {
            $comparison = $key($a) <=> $key($b);

            return $order === 'asc' ? $comparison : -$comparison;
        });

        return $rows;
    }

    /** @return array<string, mixed> */
    private static function present(array $row): array
    {
        return [
            'id' => $row['id'],
            'kind' => $row['kind'],
            'url' => $row['url'],
            'field' => $row['field'],
            'issue' => $row['issue'],
            'raw_value' => $row['raw_value'],
            'error_reason' => $row['error_reason'] ?? null,
            'http_status' => $row['http_status'] ?? null,
            'scrape_run_id' => $row['scrape_run_id'],
            'shop_book_id' => $row['shop_book_id'],
            'shop_book_title' => $row['shop_book_title'],
            'shop_id' => $row['shop_id'] ?? null,
            'shop_name' => $row['shop_name'] ?? null,
            'url_type' => $row['url_type'] ?? null,
            'book_type' => $row['book_type'] ?? null,
            'lifecycle_state' => $row['lifecycle_state'],
            'severity' => $row['severity'],
            'added_at' => self::iso($row['added_at']),
            'added_ago' => RunPresenter::relative(
                $row['added_at'] !== null ? Carbon::parse($row['added_at']) : null
            ),
            'description' => IssueMetadata::description((string) $row['issue']),
        ];
    }

    /**
     * Bucket counts under the same filters as the list, for the stat strip.
     *
     * @return array<string, int>
     */
    private function lifecycleCounts(
        ?int $shopId,
        string $issueType,
        ?int $runId,
        string $search,
        string $severity,
    ): array {
        $query = DB::table('validation_issues as vi');

        if ($shopId !== null) {
            // Filtered on the issue's own shop_id, not the run's — an issue
            // outlives the run that found it.
            $query->where('vi.shop_id', $shopId);
        }
        if ($issueType !== '') {
            $query->where('vi.issue', $issueType);
        }
        if ($runId !== null) {
            $query->where('vi.last_seen_run_id', $runId);
        }
        if ($severity !== '') {
            $query->whereIn('vi.issue', IssueMetadata::typesWithSeverity($severity));
        }
        if ($search !== '') {
            $like = "%{$search}%";
            $query->leftJoin('shop_books as sb', 'sb.id', '=', 'vi.shop_book_id')
                ->where(fn ($q) => $q->where('vi.url', 'ilike', $like)
                    ->orWhere('sb.title', 'ilike', $like));
        }

        $counts = $query->select('vi.lifecycle_state')
            ->selectRaw('count(vi.id) as cnt')
            ->groupBy('vi.lifecycle_state')
            ->pluck('cnt', 'lifecycle_state')
            ->all();

        return [
            'new' => (int) ($counts['new'] ?? 0),
            'acknowledged' => (int) ($counts['acknowledged'] ?? 0),
            'snoozed' => (int) ($counts['snoozed'] ?? 0),
            'resolved' => (int) ($counts['resolved'] ?? 0),
            'total' => array_sum(array_map('intval', $counts)),
        ];
    }

    /** "all" and "any" are the UI's no-filter sentinels. */
    private static function filterValue(mixed $value): ?string
    {
        $value = is_string($value) ? $value : '';

        return ($value === '' || $value === 'all' || $value === 'any') ? null : $value;
    }

    private static function placeholders(array $values): string
    {
        return implode(', ', array_fill(0, count($values), '?'));
    }

    private static function iso(mixed $timestamp): ?string
    {
        if ($timestamp === null) {
            return null;
        }
        $dt = Carbon::parse($timestamp)->utc();

        return $dt->micro === 0
            ? $dt->format('Y-m-d\TH:i:sP')
            : $dt->format('Y-m-d\TH:i:s.uP');
    }

    // -------------------------------------------------------- grouped view

    /**
     * Aggregated counts for the grouped toggle.
     *
     * group_by=type       -> one row per issue type across all shops
     * group_by=type_shop  -> one row per (issue type, shop)
     */
    public function groups(Request $request): array
    {
        $groupBy = (string) $request->query('group_by', 'type');
        $isTypeShop = $groupBy === 'type_shop';
        $state = (string) $request->query('state', '');
        $runId = (int) $request->query('run_id', 0) ?: null;

        $shopName = (string) $request->query('shop', '');
        $shopId = null;
        if ($shopName !== '') {
            // Unknown shop leaves the scope unfiltered, matching Python.
            $shopId = Shop::where('name', $shopName)->value('id');
        }

        $query = DB::table('validation_issues as vi')
            ->select('vi.issue as issue_type')
            ->selectRaw('count(*) as total')
            ->selectRaw("count(*) filter (where vi.lifecycle_state = 'new') as cnt_new")
            ->selectRaw("count(*) filter (where vi.lifecycle_state = 'acknowledged') as cnt_acknowledged")
            ->selectRaw("count(*) filter (where vi.lifecycle_state = 'snoozed') as cnt_snoozed")
            ->selectRaw("count(*) filter (where vi.lifecycle_state = 'resolved') as cnt_resolved");

        if ($isTypeShop) {
            $query->addSelect(['s.name as shop_name', 's.id as shop_id_val'])
                ->leftJoin('shops as s', 's.id', '=', 'vi.shop_id');
        }

        if ($shopId !== null) {
            $query->where('vi.shop_id', $shopId);
        }
        if (in_array($state, self::LIFECYCLE_STATES, true)) {
            $query->where('vi.lifecycle_state', $state);
        }
        if ($runId !== null) {
            $query->where('vi.last_seen_run_id', $runId);
        }

        if ($isTypeShop) {
            $query->groupBy('vi.issue', 's.name', 's.id')
                ->orderByRaw('count(*) desc')
                ->orderBy('vi.issue');
        } else {
            $query->groupBy('vi.issue')->orderByRaw('count(*) desc');
        }

        return [
            'groups' => $query->get()->map(fn (object $r): array => [
                'issue_type' => $r->issue_type,
                'shop_name' => $isTypeShop ? $r->shop_name : null,
                'shop_id' => $isTypeShop ? $r->shop_id_val : null,
                'severity' => IssueMetadata::severity((string) $r->issue_type),
                'total' => (int) $r->total,
                'by_state' => [
                    'new' => (int) $r->cnt_new,
                    'acknowledged' => (int) $r->cnt_acknowledged,
                    'snoozed' => (int) $r->cnt_snoozed,
                    'resolved' => (int) $r->cnt_resolved,
                ],
            ])->all(),
            'group_by' => $groupBy,
        ];
    }

    /**
     * Per-day counts per issue type, for the sparklines.
     *
     * Dated by the last-seen run's started_at: validation_issues has no
     * created_at of its own.
     *
     * @return array<string, list<int>>|\stdClass
     */
    public function trend(Request $request): mixed
    {
        $days = max(1, (int) $request->query('days', 14));
        $state = (string) $request->query('state', 'new');

        $end = Carbon::now('UTC')->startOfDay();
        $start = $end->copy()->subDays($days - 1);

        $query = DB::table('validation_issues as vi')
            ->join('scrape_runs as sr', 'sr.id', '=', 'vi.last_seen_run_id')
            ->select('vi.issue as issue_type')
            ->selectRaw('cast(sr.started_at as date) as day')
            ->selectRaw('count(*) as cnt')
            ->where('sr.started_at', '>=', $start)
            ->groupBy('vi.issue', DB::raw('cast(sr.started_at as date)'));

        if ($state !== '') {
            $query->where('vi.lifecycle_state', $state);
        }

        $byKey = [];
        $types = [];
        foreach ($query->get() as $row) {
            $byKey[$row->issue_type . '|' . $row->day] = (int) $row->cnt;
            $types[$row->issue_type] = true;
        }

        $result = [];
        foreach (array_keys($types) as $type) {
            $series = [];
            for ($i = 0; $i < $days; $i++) {
                $day = $start->copy()->addDays($i)->toDateString();
                $series[] = $byKey[$type . '|' . $day] ?? 0;
            }
            $result[$type] = $series;
        }

        // An empty PHP array encodes as `[]`, but this endpoint is a map:
        // the frontend does Object.entries() on it, and Python returns `{}`.
        return $result === [] ? new \stdClass() : $result;
    }

    // --------------------------------------------------------------- detail

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function show(int $issueId): mixed
    {
        $row = DB::table('validation_issues as vi')
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

        if ($row === null) {
            return response()->json(['detail' => 'Issue not found'], 404);
        }

        // The FK is not always set on older rows, so fall back to matching
        // the URL within the run's shop.
        $discoveredUrlId = $row->discovered_url_id;
        $discovered = null;
        if ($discoveredUrlId === null && $row->url) {
            $discovered = DB::table('discovered_urls')
                ->where('url', $row->url)
                ->where('shop_id', $row->run_shop_id)
                ->first();
            $discoveredUrlId = $discovered->id ?? null;
        }

        // Likewise the shop_book link: reachable through the URL row when the
        // issue predates the link.
        $shopBook = $row->sb_id !== null ? $row : null;
        if ($shopBook === null) {
            $viaUrl = $discovered->shop_book_id
                ?? ($discoveredUrlId !== null
                    ? DB::table('discovered_urls')->where('id', $discoveredUrlId)->value('shop_book_id')
                    : null);
            if ($viaUrl !== null) {
                $book = DB::table('shop_books')->where('id', $viaUrl)->first();
                if ($book !== null) {
                    $shopBook = (object) [
                        'sb_id' => $book->id,
                        'sb_title' => $book->title,
                        'sb_isbn' => $book->isbn,
                        'sb_book_id' => $book->book_id,
                    ];
                }
            }
        }

        return [
            'id' => (int) $row->id,
            'kind' => self::KIND_VALIDATION,
            'url' => $row->url,
            'field' => $row->field,
            'issue' => $row->issue,
            'raw_value' => $row->raw_value,
            'scrape_run_id' => $row->last_seen_run_id,
            'shop_book_id' => $row->shop_book_id ?? ($shopBook->sb_id ?? null),
            'discovered_url_id' => $discoveredUrlId,
            'shop_book_title' => $shopBook->sb_title ?? null,
            'shop_name' => $row->shop_name,
            'lifecycle_state' => $row->lifecycle_state,
            'acknowledged_at' => self::iso($row->acknowledged_at),
            'severity' => IssueMetadata::severity((string) $row->issue),
            'added_at' => self::iso($row->run_started_at),
            'added_ago' => RunPresenter::relative(
                $row->run_started_at !== null ? Carbon::parse($row->run_started_at) : null
            ),
            'description' => IssueMetadata::description((string) $row->issue),
            'match_context' => self::matchContext($row, $shopBook),
        ];
    }

    /**
     * Extra context for match_isbn_drift so the UI can label the pair
     * ("shop says X, canonical Y — titled Z") instead of showing the bare
     * `X vs Y` raw_value.
     *
     * @return array<string, mixed>|null
     */
    private static function matchContext(object $row, ?object $shopBook): ?array
    {
        if ($row->issue !== 'match_isbn_drift' || $shopBook === null
            || ($shopBook->sb_book_id ?? null) === null) {
            return null;
        }

        $bookId = $shopBook->sb_book_id;
        $canonical = DB::table('books')->where('id', $bookId)->first();
        $isbns = DB::table('book_isbns')
            ->where('book_id', $bookId)
            ->orderByDesc('isbn_type')
            ->pluck('isbn')
            ->all();

        $parts = explode(' vs ', (string) ($row->raw_value ?? ''), 2);

        return [
            'sb_isbn' => trim($parts[0] ?? '') ?: $shopBook->sb_isbn,
            'book_isbn' => trim($parts[1] ?? '') ?: null,
            'book_id' => $bookId,
            'book_title' => $canonical->title ?? null,
            'book_isbns' => $isbns,
        ];
    }
}
