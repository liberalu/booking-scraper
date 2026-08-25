<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use BookScraper\Models\ScrapeRun;
use BookScraper\Runs\RunEvent;
use BookScraper\Runs\RunFailsafe;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * Operator actions on a run row.
 *
 * Stop / pause / resume are DB-mediated: they only flip `scrape_runs.status`
 * and the spider observes the transition on its next heartbeat tick. That is
 * what makes them portable — no signal, no pid, no container exec.
 */
final class RunMutationsController
{
    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function stop(int $runId): mixed
    {
        $run = ScrapeRun::find($runId);
        if ($run === null) {
            return response()->json(['detail' => 'Run not found'], 404);
        }
        // Idempotent: an already-stopping or terminal run reports its
        // current status instead of erroring.
        if ($run->status === 'running') {
            DB::transaction(function () use ($runId): void {
                ScrapeRun::whereKey($runId)->update(['status' => 'stopping']);
                RunFailsafe::recordEvent(
                    $runId,
                    RunEvent::STOP_REQUESTED,
                    null,
                    RunEvent::ACTOR_OPERATOR,
                );
            });

            return ['run_id' => $runId, 'status' => 'stopping'];
        }

        return ['run_id' => $runId, 'status' => $run->status];
    }

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function pause(int $runId): mixed
    {
        $run = ScrapeRun::find($runId);
        if ($run === null) {
            return response()->json(['detail' => 'Run not found'], 404);
        }
        if ($run->status === 'running') {
            DB::transaction(function () use ($runId): void {
                ScrapeRun::whereKey($runId)->update(['status' => 'paused']);
                RunFailsafe::recordEvent(
                    $runId,
                    RunEvent::PAUSED,
                    ['previous_status' => 'running'],
                    RunEvent::ACTOR_OPERATOR,
                );
            });

            return ['run_id' => $runId, 'status' => 'paused'];
        }

        return ['run_id' => $runId, 'status' => $run->status];
    }

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function resume(int $runId): mixed
    {
        $run = ScrapeRun::find($runId);
        if ($run === null) {
            return response()->json(['detail' => 'Run not found'], 404);
        }
        if ($run->status === 'paused') {
            DB::transaction(function () use ($runId): void {
                ScrapeRun::whereKey($runId)->update([
                    'status' => 'running',
                    // A long pause leaves last_heartbeat hours stale; without
                    // this the reaper kills the run the moment it resumes.
                    'last_heartbeat' => Carbon::now('UTC'),
                ]);
                RunFailsafe::recordEvent(
                    $runId,
                    RunEvent::RESUMED,
                    ['previous_status' => 'paused'],
                    RunEvent::ACTOR_OPERATOR,
                );
            });

            return ['run_id' => $runId, 'status' => 'running'];
        }

        return ['run_id' => $runId, 'status' => $run->status];
    }

    /**
     * Mark one failure bucket `acknowledged` so it stops surfacing.
     *
     * The filter contract mirrors /retry and /urls: the bucket's
     * error_reason + http_status, with *_is_null flags for the nullable
     * buckets. History rows are updated too, so a retried-and-still-failing
     * URL does not pop back as `new`.
     *
     * @return array<string, mixed>|\Illuminate\Http\JsonResponse
     */
    public function ackFailures(Request $request, int $runId): mixed
    {
        if (ScrapeRun::find($runId) === null) {
            return response()->json(['detail' => 'Run not found'], 404);
        }

        $errorReason = (string) $request->query('error_reason', '');
        $reasonIsNull = self::flag($request, 'error_reason_is_null');
        $httpStatus = $request->query('http_status');
        $statusIsNull = self::flag($request, 'http_status_is_null');
        $note = (string) $request->query('note', '');

        $filter = static function ($q) use (
            $runId,
            $errorReason,
            $reasonIsNull,
            $httpStatus,
            $statusIsNull
        ) {
            $q->where('run_id', $runId);
            if ($reasonIsNull) {
                $q->whereNull('error_reason');
            } elseif ($errorReason !== '') {
                $q->where('error_reason', $errorReason);
            }
            if ($statusIsNull) {
                $q->whereNull('http_status');
            } elseif ($httpStatus !== null && $httpStatus !== '') {
                $q->where('http_status', (int) $httpStatus);
            }

            return $q;
        };

        $matches = $filter(DB::table('scrape_failures'))->count();
        if ($matches === 0) {
            return response()->json([
                'detail' => 'No matching scrape_failures rows to acknowledge.',
            ], 400);
        }

        $values = [
            'lifecycle_state' => 'acknowledged',
            'acknowledged_at' => Carbon::now('UTC'),
        ];
        if ($note !== '') {
            $values['acknowledged_note'] = $note;
        }
        $filter(DB::table('scrape_failures'))->update($values);

        return [
            'acknowledged' => $matches,
            'run_id' => $runId,
            'error_reason' => $reasonIsNull ? null : ($errorReason ?: null),
            'http_status' => ($statusIsNull || $httpStatus === null || $httpStatus === '')
                ? null
                : (int) $httpStatus,
        ];
    }

    /** FastAPI accepts true/1/yes/on for a bool query param. */
    private static function flag(Request $request, string $key): bool
    {
        $raw = $request->query($key);
        if ($raw === null) {
            return false;
        }

        return in_array(strtolower((string) $raw), ['true', '1', 'yes', 'on'], true);
    }
}
