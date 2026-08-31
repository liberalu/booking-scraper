<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\Request\IssueQueryInput;
use App\Models\ValidationIssue;
use App\Support\IssueMetadata;
use App\Support\Queries;
use App\Support\RunPresenter;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use stdClass;

/**
 * @phpstan-type UnifiedIssue array{
 *     id: int, kind: string, url: string, field: string, issue: string,
 *     raw_value: string|null, error_reason: string|null, http_status: int|null,
 *     scrape_run_id: int, shop_book_id: int|null, shop_book_title: string|null,
 *     shop_id: int|null, shop_name: string|null, url_type: string|null,
 *     book_type: string|null, lifecycle_state: string, severity: string,
 *     added_at: string|null
 * }
 */
final readonly class IssueReadRepository
{
    private const array SORTABLE = ['age', 'id', 'type', 'shop', 'book', 'sev'];

    public function __construct(
        private ValidationIssueListRepository $validationIssues = new ValidationIssueListRepository,
        private ScrapeFailureListRepository $scrapeFailures = new ScrapeFailureListRepository,
        private IssueAggregateReadRepository $aggregates = new IssueAggregateReadRepository,
        private IssueDetailReadRepository $details = new IssueDetailReadRepository,
    ) {}

    /** @return array<string, mixed> */
    public function index(IssueQueryInput $input): array
    {
        $state = $input->state ?? 'new';
        $issueType = $input->issueType;
        $runId = $input->runId;
        $severity = $input->severity;
        $urlType = $this->filterValue($input->urlType);
        $bookType = $this->filterValue($input->bookType);
        $search = $input->search;
        $sortBy = in_array($input->sortBy, self::SORTABLE, true) ? $input->sortBy : 'age';
        $order = $input->order === 'asc' ? 'asc' : 'desc';
        $page = max(1, $input->page ?? 1);
        $perPage = max(1, min($input->perPage ?? 30, 200));
        $kind = in_array($input->kind, ['all', 'validation', 'scrape_failure'], true)
            ? $input->kind
            : 'all';
        $shopId = $this->shopId($input->shop);
        $helperPage = $kind === 'all' ? 1 : $page;
        $helperPerPage = $kind === 'all' ? $page * $perPage : $perPage;
        $rows = [];
        $total = 0;

        if ($kind === 'all' || $kind === 'validation') {
            [$validationRows, $validationTotal] = $this->validationIssues->fetch(
                $state, $shopId, $issueType, $runId, $search, $severity,
                $urlType, $bookType, $order, $sortBy, $helperPage, $helperPerPage,
            );
            $rows = [...$rows, ...$validationRows];
            $total += $validationTotal;
        }
        if ($kind === 'all' || $kind === 'scrape_failure') {
            [$failureRows, $failureTotal] = $this->scrapeFailures->fetch(
                $state, $shopId, $issueType, $runId, $search, $severity,
                $order, $sortBy, $helperPage, $helperPerPage,
            );
            $rows = [...$rows, ...$failureRows];
            $total += $failureTotal;
        }
        if ($kind === 'all') {
            $rows = array_slice($this->sort($rows, $sortBy, $order), ($page - 1) * $perPage, $perPage);
        }

        return [
            'issues' => array_map($this->present(...), $rows),
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'pages' => Queries::pageCount($total, $perPage),
            'counts' => $this->lifecycleCounts($shopId, $issueType, $runId, $search, $severity),
            'kind' => $kind,
        ];
    }

    /** @return array<string, mixed> */
    public function groups(IssueQueryInput $input): array
    {
        return self::map($this->aggregates->groups($input));
    }

    /** @return array<string, list<int>>|stdClass */
    public function trend(IssueQueryInput $input): array|stdClass
    {
        return $this->aggregates->trend($input);
    }

    /** @return array<string, mixed> */
    public function show(ValidationIssue $issue): array
    {
        return self::map($this->details->show($issue));
    }

    private function shopId(string $shopName): ?int
    {
        if ($shopName === '' || $shopName === 'all') {
            return null;
        }

        return DatabaseRow::nullable(
            DB::table('shops')->select('id')->where('name', $shopName)->first(),
        )?->int('id') ?? -1;
    }

    /**
     * @param  list<UnifiedIssue>  $rows
     * @return list<UnifiedIssue>
     */
    private function sort(array $rows, string $sortBy, string $order): array
    {
        $severityRank = ['critical' => 1, 'warning' => 2];
        usort($rows, function (array $left, array $right) use ($sortBy, $order, $severityRank): int {
            $comparison = $this->sortKey($left, $sortBy, $severityRank)
                <=> $this->sortKey($right, $sortBy, $severityRank);

            return $order === 'asc' ? $comparison : -$comparison;
        });

        return $rows;
    }

    /**
     * @param  UnifiedIssue  $row
     * @return array<string, mixed>
     */
    private function present(array $row): array
    {
        $addedAt = $row['added_at'] === null ? null : Carbon::parse($row['added_at']);

        return [
            'id' => $row['id'],
            'kind' => $row['kind'],
            'url' => $row['url'],
            'field' => $row['field'],
            'issue' => $row['issue'],
            'raw_value' => $row['raw_value'],
            'error_reason' => $row['error_reason'],
            'http_status' => $row['http_status'],
            'scrape_run_id' => $row['scrape_run_id'],
            'shop_book_id' => $row['shop_book_id'],
            'shop_book_title' => $row['shop_book_title'],
            'shop_id' => $row['shop_id'],
            'shop_name' => $row['shop_name'],
            'url_type' => $row['url_type'],
            'book_type' => $row['book_type'],
            'lifecycle_state' => $row['lifecycle_state'],
            'severity' => $row['severity'],
            'added_at' => RunPresenter::iso($addedAt),
            'added_ago' => RunPresenter::relative($addedAt),
            'description' => IssueMetadata::description($row['issue']),
        ];
    }

    /** @return array{new: int, acknowledged: int, snoozed: int, resolved: int, total: int} */
    private function lifecycleCounts(?int $shopId, string $issueType, ?int $runId, string $search, string $severity): array
    {
        $query = DB::table('validation_issues as vi');
        if ($shopId !== null) {
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
                ->where(fn (Builder $nested): Builder => $nested->where('vi.url', 'ilike', $like)
                    ->orWhere('sb.title', 'ilike', $like));
        }
        $counts = [];
        foreach ($query->select('vi.lifecycle_state')->selectRaw('count(vi.id) as cnt')
            ->groupBy('vi.lifecycle_state')->get() as $raw) {
            $row = DatabaseRow::from($raw);
            $counts[$row->string('lifecycle_state')] = $row->int('cnt');
        }

        return [
            'new' => $counts['new'] ?? 0,
            'acknowledged' => $counts['acknowledged'] ?? 0,
            'snoozed' => $counts['snoozed'] ?? 0,
            'resolved' => $counts['resolved'] ?? 0,
            'total' => array_sum($counts),
        ];
    }

    private function filterValue(mixed $value): ?string
    {
        $value = is_string($value) ? $value : '';

        return in_array($value, ['', 'all', 'any'], true) ? null : $value;
    }

    /**
     * @param  UnifiedIssue  $row
     * @param  array<string, int>  $severityRank
     */
    private function sortKey(array $row, string $sortBy, array $severityRank): int|string
    {
        return match ($sortBy) {
            'id' => $row['id'],
            'type' => mb_strtolower($row['issue'], 'UTF-8'),
            'shop' => mb_strtolower($row['shop_name'] ?? '', 'UTF-8'),
            'book' => mb_strtolower($row['shop_book_title'] ?? '', 'UTF-8'),
            'sev' => $severityRank[$row['severity']] ?? 2,
            default => $row['added_at'] ?? '0001-01-01 00:00:00',
        };
    }

    /**
     * @param  array<mixed>  $value
     * @return array<string, mixed>
     */
    private static function map(array $value): array
    {
        $map = [];
        foreach ($value as $key => $item) {
            if (is_string($key)) {
                $map[$key] = $item;
            }
        }

        return $map;
    }
}
