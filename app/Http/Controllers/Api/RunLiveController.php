<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Support\RunPresenter;
use App\Models\ScrapeRun;
use App\Runs\RunReconciler;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * GET /api/runs/{id}/live — live snapshot, polled every ~2s while running.
 *
 * Everything is derived from `scrape_url_items`, `scrape_failures` and
 * `scrape_runs` — no extra tables, no in-memory state, so it survives a
 * dashboard restart.
 */
final class RunLiveController
{
    /** Heartbeat older than this means the process is gone. */
    private const DEAD_HEARTBEAT_S = 30;

    /** Rate window. Short enough to reflect "now", long enough to smooth. */
    private const RATE_WINDOW_S = 60;

    /**
     * A stranded run can hold hundreds of orphaned `processing` rows, which
     * would push the rest of the page out of reach.
     */
    private const IN_FLIGHT_CAP = 50;

    /** DOWNLOAD_TIMEOUT (15s) × 2 — beyond this an in-flight row is hung. */
    private const HUNG_THRESHOLD_S = 30.0;

    /** How many prior runs the recurrence count looks back over. */
    private const RECURRENCE_LOOKBACK_RUNS = 5;

    private const ACTIVITY_LIMIT = 20;

    private const FAILURE_EXAMPLES = 3;

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function __invoke(Request $request, int $runId): mixed
    {
        $run = ScrapeRun::find($runId);
        if ($run === null) {
            return response()->json(['detail' => 'Run not found'], 404);
        }

        $now = Carbon::now('UTC');
        $heartbeatAge = $run->last_heartbeat !== null
            ? self::seconds($run->last_heartbeat, $now)
            : null;

        $inFlight = self::inFlight($runId, $now);
        $rate = self::rateWindow($runId);

        $health = self::health($run, $now);
        // Refine to 'stuck': the heartbeat is fresh, so the process lives,
        // but a request has been claimed longer than the network timeout
        // allows — alive and hung, which reads differently to an operator.
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
                ? self::eta($runId, $requestsPerMinute)
                : null,
            'failure_groups' => self::failureGroups($run, $request->boolean('include_acked')),
            'recent_activity' => self::recentActivity($runId, $now),
            'events' => self::events($runId),
            'retry_cap' => RunReconciler::RETRY_CAP,
        ];
    }

    /** '' for a non-running run: health only means something while live. */
    private static function health(ScrapeRun $run, Carbon $now): string
    {
        if ($run->status !== 'running') {
            return '';
        }
        $lastActivity = $run->last_heartbeat ?? $run->started_at;
        if ($lastActivity === null) {
            return 'dead';
        }

        return $lastActivity->diffInRealSeconds($now, true) > self::DEAD_HEARTBEAT_S
            ? 'dead'
            : 'healthy';
    }

    /** @return list<array<string, mixed>> */
    private static function inFlight(int $runId, Carbon $now): array
    {
        return DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'processing')
            ->orderBy('claimed_at')
            ->orderBy('id')
            ->limit(self::IN_FLIGHT_CAP)
            ->get()
            ->map(function (object $row) use ($now): array {
                $claimed = $row->claimed_at !== null ? Carbon::parse($row->claimed_at) : null;

                return [
                    'url' => $row->url,
                    'claimed_at' => self::iso($claimed),
                    'claimed_age_s' => $claimed !== null ? self::seconds($claimed, $now) : null,
                    'request_delay_s' => $row->request_delay_s !== null ? (float) $row->request_delay_s : null,
                    'delay_source' => $row->delay_source,
                    'retry_count' => (int) $row->retry_count,
                ];
            })->all();
    }

    /** @return array{window_s: int, done: int, failed: int} */
    private static function rateWindow(int $runId): array
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

    /** Minutes remaining from pending count over observed rate. */
    private static function eta(int $runId, float $requestsPerMinute): ?int
    {
        if ($requestsPerMinute <= 0) {
            // Stalled: any number here would be a fabrication.
            return null;
        }
        $pending = DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'pending')
            ->count();

        return $pending === 0 ? 0 : max(1, (int) round($pending / $requestsPerMinute));
    }

    /**
     * Failure buckets, grouped by (error_reason, http_status).
     *
     * Two filters make this "what is failing right now" rather than a
     * timeline: only each item's LATEST event counts, and the item must
     * currently be `failed` — so a URL that was retried successfully drops
     * off immediately.
     *
     * @return list<array<string, mixed>>
     */
    private static function failureGroups(ScrapeRun $run, bool $includeAcked): array
    {
        $latest = DB::table('scrape_failures')
            ->select('id', 'scrape_url_item_id', 'error_reason', 'http_status', 'lifecycle_state', 'error_detail')
            ->selectRaw(
                'row_number() over (partition by scrape_url_item_id '
                . 'order by occurred_at desc, id desc) as rn'
            )
            ->where('run_id', $run->id);

        $groups = DB::query()
            ->fromSub($latest, 'lf')
            ->join('scrape_url_items as sui', 'sui.id', '=', 'lf.scrape_url_item_id')
            ->select('lf.error_reason', 'lf.http_status')
            ->selectRaw("sum(case when lf.lifecycle_state != 'acknowledged' then 1 else 0 end) as unacked_count")
            ->selectRaw("sum(case when lf.lifecycle_state = 'acknowledged' then 1 else 0 end) as acked_count")
            ->selectRaw('max(sui.attempts) as max_attempts')
            ->selectRaw('sum(case when sui.attempts >= ? then 1 else 0 end) as capped_count', [RunReconciler::RETRY_CAP])
            ->where('lf.rn', 1)
            ->where('sui.status', 'failed')
            ->groupBy('lf.error_reason', 'lf.http_status');

        if (!$includeAcked) {
            // Hide buckets where every latest event is already acknowledged.
            $groups->havingRaw("sum(case when lf.lifecycle_state != 'acknowledged' then 1 else 0 end) > 0");
        }

        $rows = $groups
            ->orderByRaw("sum(case when lf.lifecycle_state != 'acknowledged' then 1 else 0 end) desc")
            ->orderByRaw("sum(case when lf.lifecycle_state = 'acknowledged' then 1 else 0 end) desc")
            ->get();

        if ($rows->isEmpty()) {
            return [];
        }

        // Recurrence is deliberately status-blind: the operator's question is
        // "how often does this kind of failure happen", including buckets
        // that already cleared in earlier runs.
        $priorRunIds = ScrapeRun::where('shop_id', $run->shop_id)
            ->where('id', '!=', $run->id)
            ->whereNotNull('started_at')
            ->orderByDesc('started_at')
            ->limit(self::RECURRENCE_LOOKBACK_RUNS)
            ->pluck('id')
            ->all();

        return $rows->map(function (object $row) use ($run, $priorRunIds, $includeAcked, $latest): array {
            $unacked = (int) ($row->unacked_count ?? 0);
            $acked = (int) ($row->acked_count ?? 0);

            $recurring = 0;
            if ($priorRunIds !== []) {
                $recurring = DB::table('scrape_failures')
                    ->whereIn('run_id', $priorRunIds)
                    ->where(fn ($q) => $row->error_reason === null
                        ? $q->whereNull('error_reason')
                        : $q->where('error_reason', $row->error_reason))
                    ->where(fn ($q) => $row->http_status === null
                        ? $q->whereNull('http_status')
                        : $q->where('http_status', $row->http_status))
                    ->distinct()
                    ->count('run_id');
            }

            // Examples come from the same latest-failed slice as the count,
            // so a retried-and-succeeded URL cannot appear.
            $examples = DB::query()
                ->fromSub($latest, 'lf')
                ->join('scrape_url_items as sui', 'sui.id', '=', 'lf.scrape_url_item_id')
                ->select('sui.url', 'lf.error_detail')
                ->where('lf.rn', 1)
                ->where('sui.status', 'failed')
                ->where(fn ($q) => $row->error_reason === null
                    ? $q->whereNull('lf.error_reason')
                    : $q->where('lf.error_reason', $row->error_reason))
                ->where(fn ($q) => $row->http_status === null
                    ? $q->whereNull('lf.http_status')
                    : $q->where('lf.http_status', $row->http_status))
                ->when(!$includeAcked, fn ($q) => $q->where('lf.lifecycle_state', '!=', 'acknowledged'))
                ->limit(self::FAILURE_EXAMPLES)
                ->get()
                ->map(fn (object $e): array => [
                    'url' => $e->url,
                    // Capped: a monster traceback would dominate the payload.
                    'error_detail' => $e->error_detail !== null
                        ? mb_substr((string) $e->error_detail, 0, 4000)
                        : null,
                ])->all();

            return [
                'reason' => $row->error_reason,
                'reason_display' => $row->error_reason ?: 'unknown',
                'reason_is_null' => $row->error_reason === null,
                'http' => $row->http_status,
                'http_is_null' => $row->http_status === null,
                // Preserves the pre-acknowledgement contract: the default
                // count is what is still unacked.
                'count' => $includeAcked ? $unacked + $acked : $unacked,
                'unacked_count' => $unacked,
                'acked_count' => $acked,
                'recurring_in_runs' => $recurring,
                'max_attempts' => (int) ($row->max_attempts ?? 0),
                'capped_count' => (int) ($row->capped_count ?? 0),
                'examples' => $examples,
            ];
        })->all();
    }

    /** @return list<array<string, mixed>> */
    private static function recentActivity(int $runId, Carbon $now): array
    {
        $latest = DB::table('scrape_failures')
            ->select('scrape_url_item_id', 'error_reason')
            ->selectRaw(
                'row_number() over (partition by scrape_url_item_id '
                . 'order by occurred_at desc, id desc) as rn'
            )
            ->where('run_id', $runId);

        return DB::table('scrape_url_items as sui')
            ->leftJoinSub($latest, 'lf', function ($join): void {
                $join->on('lf.scrape_url_item_id', '=', 'sui.id')->where('lf.rn', 1);
            })
            ->select('sui.*', 'lf.error_reason as latest_error_reason')
            ->where('sui.run_id', $runId)
            ->whereIn('sui.status', ['done', 'failed'])
            ->whereNotNull('sui.done_at')
            ->orderByDesc('sui.done_at')
            ->orderByDesc('sui.id')
            ->limit(self::ACTIVITY_LIMIT)
            ->get()
            ->map(function (object $row) use ($now): array {
                $claimed = $row->claimed_at !== null ? Carbon::parse($row->claimed_at) : null;
                $done = $row->done_at !== null ? Carbon::parse($row->done_at) : null;

                return [
                    'url' => $row->url,
                    'status' => $row->status,
                    'http_status' => $row->http_status,
                    'error_reason' => $row->status === 'failed' ? $row->latest_error_reason : null,
                    'claimed_at' => self::iso($claimed),
                    'done_at' => self::iso($done),
                    'duration_s' => ($claimed !== null && $done !== null)
                        ? self::seconds($claimed, $done)
                        : null,
                    'done_age_s' => $done !== null ? self::seconds($done, $now) : null,
                    'request_delay_s' => $row->request_delay_s !== null ? (float) $row->request_delay_s : null,
                    'delay_source' => $row->delay_source,
                    'response_bytes' => $row->response_bytes,
                ];
            })->all();
    }

    /** @return list<array<string, mixed>> */
    private static function events(int $runId): array
    {
        return DB::table('scrape_run_events')
            ->where('run_id', $runId)
            ->orderBy('created_at')
            ->orderBy('id')
            ->get()
            ->map(fn (object $e): array => [
                'id' => (int) $e->id,
                'event_type' => $e->event_type,
                'created_at' => self::iso(
                    $e->created_at !== null ? Carbon::parse($e->created_at) : null
                ),
                'actor' => $e->actor,
                'payload' => $e->payload !== null ? json_decode((string) $e->payload, true) : null,
            ])->all();
    }

    /**
     * Seconds between two instants, at microsecond resolution.
     *
     * Python derives this from timedelta.total_seconds(), which is exact
     * because it comes from an integer microsecond count. A raw PHP float
     * subtraction yields 0.37736000000000003 for the same interval, so the
     * value is rounded to microseconds to match.
     */
    private static function seconds(Carbon $from, Carbon $to): float
    {
        return round(max(0.0, (float) $from->diffInRealSeconds($to, true)), 6);
    }

    private static function iso(?Carbon $dt): ?string
    {
        if ($dt === null) {
            return null;
        }
        $utc = $dt->utc();

        return $utc->micro === 0
            ? $utc->format('Y-m-d\TH:i:sP')
            : $utc->format('Y-m-d\TH:i:s.uP');
    }
}
