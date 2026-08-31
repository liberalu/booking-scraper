<?php

declare(strict_types=1);

namespace App\Repositories;

use App\DTO\Request\RunQueryInput;
use App\Models\ScrapeRun;
use Illuminate\Database\Query\Builder;
use Illuminate\Database\Query\JoinClause;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

final class RunLiveReadRepository
{
    private const int DEAD_HEARTBEAT_S = 30;

    private const int RATE_WINDOW_S = 60;

    private const int IN_FLIGHT_CAP = 50;

    private const float HUNG_THRESHOLD_S = 30.0;

    private const int RECURRENCE_LOOKBACK_RUNS = 5;

    private const int ACTIVITY_LIMIT = 20;

    private const int FAILURE_EXAMPLES = 3;

    /** @return array<string, mixed> */
    public function __invoke(RunQueryInput $input, ScrapeRun $run): array
    {
        $runId = $run->id;

        $now = Carbon::now('UTC');
        $heartbeatAge = $run->last_heartbeat !== null
            ? $this->seconds($run->last_heartbeat, $now)
            : null;

        $inFlight = $this->inFlight($runId, $now);
        $rate = $this->rateWindow($runId);

        $health = $this->health($run, $now);

        if ($health === 'healthy') {
            foreach ($inFlight as $row) {
                if (($row['claimed_age_s'] ?? 0.0) > self::HUNG_THRESHOLD_S) {
                    $health = 'stuck';
                    break;
                }
            }
        }

        $requestsPerMinute = $rate['window_s'] > 0
            ? ($rate['done'] / $rate['window_s']) * 60
            : 0.0;

        return [
            'run_id' => $runId,
            'status' => $run->status,
            'health' => $health,
            'last_heartbeat_age_s' => $heartbeatAge,
            'in_flight' => $inFlight,
            'rate' => $rate,
            'eta_min' => $run->status === 'running'
                ? $this->eta($runId, $requestsPerMinute)
                : null,
            'failure_groups' => $this->failureGroups($run, $input->includeAcknowledged),
            'recent_activity' => $this->recentActivity($runId, $now),
            'events' => $this->events($runId),
            'retry_cap' => RunReconcilerRepository::RETRY_CAP,
        ];
    }

    private function health(ScrapeRun $run, Carbon $now): string
    {
        if ($run->status !== 'running') {
            return '';
        }
        $lastActivity = $run->last_heartbeat ?? $run->started_at;
        if ($lastActivity === null) {
            return 'dead';
        }

        return $lastActivity->diffInSeconds($now, true) > self::DEAD_HEARTBEAT_S
            ? 'dead'
            : 'healthy';
    }

    /** @return list<array<string, mixed>> */
    private function inFlight(int $runId, Carbon $now): array
    {
        $rows = DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'processing')
            ->orderBy('claimed_at')
            ->orderBy('id')
            ->limit(self::IN_FLIGHT_CAP)
            ->get();
        $items = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $claimed = $this->time($row->nullableString('claimed_at'));
            $items[] = [
                'url' => $row->string('url'),
                'claimed_at' => $this->iso($claimed),
                'claimed_age_s' => $claimed === null ? null : $this->seconds($claimed, $now),
                'request_delay_s' => $row->nullableFloat('request_delay_s'),
                'delay_source' => $row->nullableString('delay_source'),
                'retry_count' => $row->int('retry_count'),
            ];
        }

        return $items;
    }

    /** @return array{window_s: int, done: int, failed: int} */
    private function rateWindow(int $runId): array
    {
        $cutoff = Carbon::now('UTC')->subSeconds(self::RATE_WINDOW_S);

        $count = static fn (string $status): int => DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', $status)
            ->whereNotNull('done_at')
            ->where('done_at', '>', $cutoff)
            ->count();

        return [
            'window_s' => self::RATE_WINDOW_S,
            'done' => $count('done'),
            'failed' => $count('failed'),
        ];
    }

    private function eta(int $runId, float $requestsPerMinute): ?int
    {
        if ($requestsPerMinute <= 0) {

            return null;
        }
        $pending = DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'pending')
            ->count();

        return $pending === 0 ? 0 : max(1, (int) round($pending / $requestsPerMinute));
    }

    /** @return list<array<string, mixed>> */
    private function failureGroups(ScrapeRun $run, bool $includeAcked): array
    {
        $latest = DB::table('scrape_failures')
            ->select('id', 'scrape_url_item_id', 'error_reason', 'http_status', 'lifecycle_state', 'error_detail')
            ->selectRaw(
                'row_number() over (partition by scrape_url_item_id '
                .'order by occurred_at desc, id desc) as rn'
            )
            ->where('run_id', $run->id);

        $groups = DB::query()
            ->fromSub($latest, 'lf')
            ->join('scrape_url_items as sui', 'sui.id', '=', 'lf.scrape_url_item_id')
            ->select('lf.error_reason', 'lf.http_status')
            ->selectRaw("sum(case when lf.lifecycle_state != 'acknowledged' then 1 else 0 end) as unacked_count")
            ->selectRaw("sum(case when lf.lifecycle_state = 'acknowledged' then 1 else 0 end) as acked_count")
            ->selectRaw('max(sui.attempts) as max_attempts')
            ->selectRaw('sum(case when sui.attempts >= ? then 1 else 0 end) as capped_count', [RunReconcilerRepository::RETRY_CAP])
            ->where('lf.rn', 1)
            ->where('sui.status', 'failed')
            ->groupBy('lf.error_reason', 'lf.http_status');

        if (! $includeAcked) {

            $groups->havingRaw("sum(case when lf.lifecycle_state != 'acknowledged' then 1 else 0 end) > 0");
        }

        $rows = $groups
            ->orderByRaw("sum(case when lf.lifecycle_state != 'acknowledged' then 1 else 0 end) desc")
            ->orderByRaw("sum(case when lf.lifecycle_state = 'acknowledged' then 1 else 0 end) desc")
            ->get();

        if ($rows->isEmpty()) {
            return [];
        }

        $rawPriorRunIds = DB::table('scrape_runs')
            ->where('shop_id', $run->shop_id)
            ->where('id', '!=', $run->id)
            ->whereNotNull('started_at')
            ->orderByDesc('started_at')
            ->limit(self::RECURRENCE_LOOKBACK_RUNS)
            ->pluck('id')
            ->all();
        $priorRunIds = [];
        foreach ($rawPriorRunIds as $rawId) {
            $priorRunIds[] = DatabaseRow::from(['id' => $rawId])->int('id');
        }

        $result = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $unacked = $row->nullableInt('unacked_count') ?? 0;
            $acked = $row->nullableInt('acked_count') ?? 0;
            $errorReason = $row->nullableString('error_reason');
            $httpStatus = $row->nullableInt('http_status');

            $recurring = 0;
            if ($priorRunIds !== []) {
                $recurring = DB::table('scrape_failures')
                    ->whereIn('run_id', $priorRunIds)
                    ->where(fn (Builder $q): Builder => $errorReason === null
                        ? $q->whereNull('error_reason')
                        : $q->where('error_reason', $errorReason))
                    ->where(fn (Builder $q): Builder => $httpStatus === null
                        ? $q->whereNull('http_status')
                        : $q->where('http_status', $httpStatus))
                    ->distinct()
                    ->count('run_id');
            }

            $exampleRows = DB::query()
                ->fromSub($latest, 'lf')
                ->join('scrape_url_items as sui', 'sui.id', '=', 'lf.scrape_url_item_id')
                ->select('sui.url', 'lf.error_detail')
                ->where('lf.rn', 1)
                ->where('sui.status', 'failed')
                ->where(fn (Builder $q): Builder => $errorReason === null
                    ? $q->whereNull('lf.error_reason')
                    : $q->where('lf.error_reason', $errorReason))
                ->where(fn (Builder $q): Builder => $httpStatus === null
                    ? $q->whereNull('lf.http_status')
                    : $q->where('lf.http_status', $httpStatus))
                ->when(! $includeAcked, fn (Builder $q): Builder => $q->where('lf.lifecycle_state', '!=', 'acknowledged'))
                ->limit(self::FAILURE_EXAMPLES)
                ->get();
            $examples = [];
            foreach ($exampleRows as $exampleRaw) {
                $example = DatabaseRow::from($exampleRaw);
                $detail = $example->nullableString('error_detail');
                $examples[] = [
                    'url' => $example->string('url'),
                    'error_detail' => $detail === null ? null : mb_substr($detail, 0, 4000),
                ];
            }

            $result[] = [
                'reason' => $errorReason,
                'reason_display' => $errorReason ?? 'unknown',
                'reason_is_null' => $errorReason === null,
                'http' => $httpStatus,
                'http_is_null' => $httpStatus === null,

                'count' => $includeAcked ? $unacked + $acked : $unacked,
                'unacked_count' => $unacked,
                'acked_count' => $acked,
                'recurring_in_runs' => $recurring,
                'max_attempts' => $row->nullableInt('max_attempts') ?? 0,
                'capped_count' => $row->nullableInt('capped_count') ?? 0,
                'examples' => $examples,
            ];
        }

        return $result;
    }

    /** @return list<array<string, mixed>> */
    private function recentActivity(int $runId, Carbon $now): array
    {
        $latest = DB::table('scrape_failures')
            ->select('scrape_url_item_id', 'error_reason')
            ->selectRaw(
                'row_number() over (partition by scrape_url_item_id '
                .'order by occurred_at desc, id desc) as rn'
            )
            ->where('run_id', $runId);

        $rows = DB::table('scrape_url_items as sui')
            ->leftJoinSub($latest, 'lf', function (JoinClause $join): void {
                $join->on('lf.scrape_url_item_id', '=', 'sui.id')->where('lf.rn', 1);
            })
            ->select('sui.*', 'lf.error_reason as latest_error_reason')
            ->where('sui.run_id', $runId)
            ->whereIn('sui.status', ['done', 'failed'])
            ->whereNotNull('sui.done_at')
            ->orderByDesc('sui.done_at')
            ->orderByDesc('sui.id')
            ->limit(self::ACTIVITY_LIMIT)
            ->get();
        $activity = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $claimed = $this->time($row->nullableString('claimed_at'));
            $done = $this->time($row->nullableString('done_at'));
            $status = $row->string('status');
            $activity[] = [
                'url' => $row->string('url'),
                'status' => $status,
                'http_status' => $row->nullableInt('http_status'),
                'error_reason' => $status === 'failed' ? $row->nullableString('latest_error_reason') : null,
                'claimed_at' => $this->iso($claimed),
                'done_at' => $this->iso($done),
                'duration_s' => $claimed !== null && $done !== null
                    ? $this->seconds($claimed, $done)
                    : null,
                'done_age_s' => $done === null ? null : $this->seconds($done, $now),
                'request_delay_s' => $row->nullableFloat('request_delay_s'),
                'delay_source' => $row->nullableString('delay_source'),
                'response_bytes' => $row->nullableInt('response_bytes'),
            ];
        }

        return $activity;
    }

    /** @return list<array<string, mixed>> */
    private function events(int $runId): array
    {
        $rows = DB::table('scrape_run_events')
            ->where('run_id', $runId)
            ->orderBy('created_at')
            ->orderBy('id')
            ->get();
        $events = [];
        foreach ($rows as $raw) {
            $row = DatabaseRow::from($raw);
            $payload = $row->nullableString('payload');
            $events[] = [
                'id' => $row->int('id'),
                'event_type' => $row->string('event_type'),
                'created_at' => $this->iso($this->time($row->nullableString('created_at'))),
                'actor' => $row->nullableString('actor'),
                'payload' => $payload === null ? null : json_decode($payload, true),
            ];
        }

        return $events;
    }

    private function seconds(Carbon $from, Carbon $to): float
    {
        return round(max(0.0, $from->diffInSeconds($to, true)), 6);
    }

    private function iso(?Carbon $dt): ?string
    {
        if (! $dt instanceof Carbon) {
            return null;
        }
        $utc = $dt->utc();

        return $utc->micro === 0
            ? $utc->format('Y-m-d\TH:i:sP')
            : $utc->format('Y-m-d\TH:i:s.uP');
    }

    private function time(?string $value): ?Carbon
    {
        return $value === null ? null : Carbon::parse($value);
    }
}
