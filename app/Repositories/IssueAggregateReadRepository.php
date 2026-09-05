<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\Request\IssueQueryInput;
use App\Models\Shop;
use App\Support\IssueMetadata;
use Illuminate\Support\Facades\Date;
use Illuminate\Support\Facades\DB;
use stdClass;

final class IssueAggregateReadRepository
{
    private const array LIFECYCLE_STATES = ['new', 'acknowledged', 'snoozed', 'resolved'];

    /** @return array<string, mixed> */
    public function groups(IssueQueryInput $input): array
    {
        $groupBy = $input->groupBy ?? 'type';
        $isTypeShop = $groupBy === 'type_shop';
        $state = $input->state ?? '';
        $runId = $input->runId;

        $shopName = $input->shop;
        $shopId = null;
        if ($shopName !== '') {

            $shopId = DatabaseRow::from([
                'id' => Shop::where('name', $shopName)->value('id'),
            ])->nullableInt('id');
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

        $groups = [];
        foreach ($query->get() as $raw) {
            $r = DatabaseRow::from($raw);
            $issueType = $r->string('issue_type');
            $groups[] = [
                'issue_type' => $issueType,
                'shop_name' => $isTypeShop ? $r->nullableString('shop_name') : null,
                'shop_id' => $isTypeShop ? $r->nullableInt('shop_id_val') : null,
                'severity' => IssueMetadata::severity($issueType),
                'total' => $r->int('total'),
                'by_state' => [
                    'new' => $r->int('cnt_new'),
                    'acknowledged' => $r->int('cnt_acknowledged'),
                    'snoozed' => $r->int('cnt_snoozed'),
                    'resolved' => $r->int('cnt_resolved'),
                ],
            ];
        }

        return [
            'groups' => $groups,
            'group_by' => $groupBy,
        ];
    }

    /** @return array<string, list<int>>|stdClass */
    public function trend(IssueQueryInput $input): array|stdClass
    {
        $days = max(1, $input->days ?? 14);
        $state = $input->state ?? 'new';

        $end = Date::now('UTC')->startOfDay();
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
        foreach ($query->get() as $raw) {
            $row = DatabaseRow::from($raw);
            $type = $row->string('issue_type');
            $byKey[$type.'|'.$row->string('day')] = $row->int('cnt');
            $types[$type] = true;
        }

        $result = [];
        foreach (array_keys($types) as $type) {
            $series = [];
            for ($i = 0; $i < $days; $i++) {
                $day = $start->copy()->addDays($i)->toDateString();
                $series[] = $byKey[$type.'|'.$day] ?? 0;
            }
            $result[$type] = $series;
        }

        return $result === [] ? new stdClass : $result;
    }
}
