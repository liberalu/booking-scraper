<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\Request\IssueQueryInput;
use App\Models\ValidationIssue;
use App\Support\IssueMetadata;
use App\Support\Queries;
use App\Support\RunPresenter;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use stdClass;

/**
 * @phpstan-import-type UnifiedIssue from UnifiedIssueReadRepository
 */
final readonly class IssueReadRepository
{
    private const array SORTABLE = ['age', 'id', 'type', 'shop', 'book', 'sev'];

    public function __construct(
        private UnifiedIssueReadRepository $issues = new UnifiedIssueReadRepository,
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
        $result = $this->issues->fetch(
            $kind, $state, $shopId, $issueType, $runId, $search, $severity,
            $urlType, $bookType, $sortBy, $order, $page, $perPage,
        );

        return [
            'issues' => array_map($this->present(...), $result['rows']),
            'total' => $result['total'],
            'page' => $page,
            'per_page' => $perPage,
            'pages' => Queries::pageCount($result['total'], $perPage),
            'counts' => $result['counts'],
            'kind' => $kind,
        ];
    }

    /** @return array<string, mixed> */
    public function groups(IssueQueryInput $input): array
    {
        return $this->map($this->aggregates->groups($input));
    }

    /** @return array<string, list<int>>|stdClass */
    public function trend(IssueQueryInput $input): array|stdClass
    {
        return $this->aggregates->trend($input);
    }

    /** @return array<string, mixed> */
    public function show(ValidationIssue $issue): array
    {
        return $this->map($this->details->show($issue));
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
     * @param  UnifiedIssue  $row
     * @return array<string, mixed>
     */
    private function present(array $row): array
    {
        $addedAt = $row['added_at'] === null ? null : Date::parse($row['added_at']);

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

    private function filterValue(mixed $value): ?string
    {
        $value = is_string($value) ? $value : '';

        return in_array($value, ['', 'all', 'any'], true) ? null : $value;
    }

    /**
     * @param  array<mixed>  $value
     * @return array<string, mixed>
     */
    private function map(array $value): array
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
