<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\Request\RunQueryInput;
use App\Exceptions\ActionFailed;
use App\Models\ScrapeRun;
use App\Models\ShopBook;
use App\Support\BookPresenter;
use App\Support\Queries;
use App\Support\RunPresenter;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

final readonly class RunDetailReadRepository
{
    public function __construct(private DashboardStatisticsRepository $statistics = new DashboardStatisticsRepository) {}

    /** @return array<string, mixed> */
    public function show(ScrapeRun $run): array
    {
        $run->load('shop');
        $runId = $run->id;
        $terminal = DatabaseRow::from(['value' => $this->statistics->runTerminalCounts([$runId])[$runId] ?? null])->nullableInt('value');
        $rescrape = self::boolean($this->statistics->rescrapeFlags([$runId])[$runId] ?? false);
        $counts = $this->itemCounts($runId);
        $base = RunPresenter::toArray($run, terminalCount: $terminal, rescrape: $rescrape);
        $base['items_added'] = $counts['items_added'];
        $base['items_updated'] = $counts['items_updated'];
        $base['items'] = $counts['items_added'] + $counts['items_updated'];

        $issues = [];
        foreach (DB::table('validation_issues')->select('field', 'issue')->selectRaw('count(id) as count')
            ->where('last_seen_run_id', $runId)->groupBy('field', 'issue')->orderByDesc(DB::raw('count(id)'))->get() as $raw) {
            $row = DatabaseRow::from($raw);
            $issues[] = ['field' => $row->string('field'), 'issue' => $row->string('issue'), 'count' => $row->int('count')];
        }
        $events = [];
        foreach (DB::table('scrape_run_events')->where('run_id', $runId)->orderBy('created_at')->orderBy('id')->get() as $raw) {
            $row = DatabaseRow::from($raw);
            $createdAt = $row->nullableString('created_at');
            $payload = $row->nullableString('payload');
            $events[] = [
                'id' => $row->int('id'),
                'event_type' => $row->string('event_type'),
                'created_at' => RunPresenter::iso($createdAt === null ? null : Carbon::parse($createdAt)),
                'actor' => $row->nullableString('actor'),
                'payload' => $payload === null ? null : json_decode($payload, true),
            ];
        }

        return [
            ...$base,
            'issues' => $issues,
            'close_reason' => $this->closeReason($run),
            'pending_count' => DB::table('scrape_url_items')->where('run_id', $runId)->where('status', 'pending')->count(),
            'events' => $events,
        ];
    }

    /** @return array<string, mixed> */
    public function books(RunQueryInput $input, ScrapeRun $run): array
    {
        $runId = $run->id;
        $type = $input->type ?? 'added';
        if (! in_array($type, ['added', 'updated'], true)) {
            throw ActionFailed::badRequest(['detail' => "type must be 'added' or 'updated'"]);
        }
        $page = max(1, $input->page ?? 1);
        $perPage = max(1, min($input->perPage ?? 50, 100));
        $changedFields = [];
        if ($type === 'added') {
            $query = DB::table('shop_books')->where('created_run_id', $runId);
            $total = (clone $query)->count();
            $rows = $query->orderBy('title')->orderBy('id')->offset(($page - 1) * $perPage)->limit($perPage)->get(['id']);
        } else {
            $changed = DB::table('shop_book_changes')->select('shop_book_id')
                ->selectRaw("string_agg(distinct field, ', ') as changed_fields")
                ->where('scrape_run_id', $runId)->groupBy('shop_book_id');
            $query = DB::table('shop_books')->joinSub($changed, 'c', 'c.shop_book_id', '=', 'shop_books.id')
                ->orderBy('shop_books.title')->orderBy('shop_books.id');
            $total = DB::query()->fromSub($changed, 'c')->count();
            $rows = $query->offset(($page - 1) * $perPage)->limit($perPage)->get(['shop_books.id', 'c.changed_fields']);
        }
        $ids = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $id = $row->int('id');
            $ids[] = $id;
            if ($type === 'updated') {
                $changedFields[$id] = $row->nullableString('changed_fields');
            }
        }
        $models = ShopBook::whereIn('id', $ids)->with('shop')->get()->keyBy('id');
        $books = [];
        foreach ($ids as $id) {
            $book = $models->get($id);
            if (! $book instanceof ShopBook) {
                continue;
            }
            $presented = BookPresenter::toArray($book);
            if ($type === 'updated') {
                $presented['changed_fields'] = $changedFields[$id] ?? null;
            }
            $books[] = $presented;
        }

        return ['books' => $books, 'total' => $total, 'page' => $page, 'pages' => Queries::pageCount($total, $perPage)];
    }

    private function closeReason(ScrapeRun $run): ?string
    {
        if ($run->status === 'completed') {
            return $run->error_count > 0 ? 'completed_with_errors' : 'completed_ok';
        }
        if ($run->status !== 'failed') {
            return null;
        }
        $reason = DB::table('validation_issues')->where('last_seen_run_id', $run->id)
            ->where('issue', 'scrape_run_failed')->orderByDesc('id')->value('raw_value');
        $value = DatabaseRow::from(['reason' => $reason])->nullableString('reason');

        return $value === null || $value === '' ? 'failed' : $value;
    }

    /** @return array{items_added: int, items_updated: int} */
    private function itemCounts(int $runId): array
    {
        return [
            'items_added' => DB::table('shop_books')->where('created_run_id', $runId)->count(),
            'items_updated' => DB::table('shop_book_changes')->where('scrape_run_id', $runId)
                ->distinct('shop_book_id')->count('shop_book_id'),
        ];
    }

    private static function boolean(mixed $value): bool
    {
        return $value === true || $value === 1 || $value === '1' || $value === 't' || $value === 'true';
    }
}
