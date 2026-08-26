<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use BookScraper\Models\CronJob;
use BookScraper\Models\Shop;
use Cron\CronExpression;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

/**
 * Create / edit / delete / toggle scheduled jobs.
 *
 * Pure DB writes. `runs:schedule` reads these rows every tick and fires what
 * is due, so nothing here touches a scheduler directly — and an edit takes
 * effect within a tick rather than at the next restart, which is what the
 * crontab this replaced required.
 */
final class CronMutationsController
{
    private const PHASES = ['discover', 'scan'];

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function store(Request $request): mixed
    {
        $shop = Shop::where('name', (string) $request->input('shop', ''))->first();
        if ($shop === null) {
            return response()->json(['detail' => 'Shop not found'], 404);
        }
        $phase = (string) $request->input('phase', '');
        if (!in_array($phase, self::PHASES, true)) {
            return response()->json(
                ['detail' => "phase must be 'discover' or 'scan'"],
                422
            );
        }
        $expression = (string) $request->input('cron_expression', '');
        if (($bad = self::cronError($expression)) !== null) {
            return response()->json(['detail' => $bad], 422);
        }

        $chainToId = $request->input('chain_to_id');
        $chainToId = $chainToId === null ? null : (int) $chainToId;
        if ($chainToId !== null && CronJob::find($chainToId) === null) {
            return response()->json(['detail' => 'Chain target job not found'], 404);
        }
        // A brand-new job has no id, so it cannot be part of a cycle yet —
        // Python skips the walk here for the same reason.

        $strategy = trim((string) $request->input('strategy', '')) ?: null;
        $job = new CronJob();
        $job->shop_id = $shop->id;
        $job->phase = $phase;
        $job->strategy = $strategy;
        $job->args = '';
        $job->cron_expression = $expression;
        $job->enabled = true;
        $job->chain_to_job_id = $chainToId;
        $job->save();

        return [
            'id' => $job->id,
            'name' => "{$shop->name}.{$job->phase}." . ($strategy ?? 'default'),
        ];
    }

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function update(Request $request, int $jobId): mixed
    {
        $job = CronJob::find($jobId);
        if ($job === null) {
            return response()->json(['detail' => 'Job not found'], 404);
        }

        $expression = $request->input('cron_expression');
        if ($expression !== null && ($bad = self::cronError((string) $expression)) !== null) {
            return response()->json(['detail' => $bad], 422);
        }

        $fields = [];
        if ($expression !== null) {
            $fields['cron_expression'] = (string) $expression;
        }

        $phase = $request->input('phase');
        if ($phase !== null) {
            if (!in_array((string) $phase, self::PHASES, true)) {
                return response()->json(
                    ['detail' => "phase must be 'discover' or 'scan'"],
                    422
                );
            }
            $fields['phase'] = (string) $phase;
        }

        $strategy = $request->input('strategy');
        if ($strategy !== null) {
            $fields['strategy'] = trim((string) $strategy) ?: null;
        }

        $chainToId = $request->input('chain_to_id');
        $chainToId = $chainToId === null ? null : (int) $chainToId;
        $clearChain = (bool) $request->input('clear_chain', false);
        if ($chainToId !== null && $clearChain) {
            return response()->json(
                ['detail' => 'Provide chain_to_id or clear_chain, not both'],
                422
            );
        }
        if ($chainToId !== null) {
            if ($chainToId === $jobId) {
                return response()->json(
                    ['detail' => 'A job cannot chain to itself'],
                    422
                );
            }
            if (CronJob::find($chainToId) === null) {
                return response()->json(['detail' => 'Chain target job not found'], 404);
            }
            if (self::wouldCycle($jobId, $chainToId)) {
                return response()->json(
                    ['detail' => 'Chain would create a cycle'],
                    422
                );
            }
            $fields['chain_to_job_id'] = $chainToId;
        } elseif ($clearChain) {
            $fields['chain_to_job_id'] = null;
        }

        if ($fields !== []) {
            CronJob::whereKey($jobId)->update($fields);
        }

        return ['id' => $jobId];
    }

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function destroy(int $jobId): mixed
    {
        if (CronJob::find($jobId) === null) {
            return response()->json(['detail' => 'Job not found'], 404);
        }

        // Deleting a chain target would silently SET NULL on its dependents
        // and break the chain, so refuse and name them.
        $dependents = DB::table('cron_jobs as cj')
            ->join('shops as s', 's.id', '=', 'cj.shop_id')
            ->where('cj.chain_to_job_id', $jobId)
            ->get(['cj.id', 'cj.phase', 'cj.strategy', 's.name']);

        if ($dependents->isNotEmpty()) {
            return response()->json([
                'detail' => [
                    'message' => 'Cannot delete: other schedules chain to this one.',
                    'dependents' => $dependents->map(static fn ($d): array => [
                        'id' => (int) $d->id,
                        'name' => "{$d->name}.{$d->phase}." . ($d->strategy ?: 'default'),
                    ])->all(),
                ],
            ], 409);
        }

        CronJob::whereKey($jobId)->delete();

        return ['id' => $jobId];
    }

    /** @return array<string, mixed>|\Illuminate\Http\JsonResponse */
    public function toggle(int $jobId): mixed
    {
        $job = CronJob::find($jobId);
        if ($job === null) {
            return response()->json(['detail' => 'Job not found'], 404);
        }
        $enabled = !$job->enabled;
        CronJob::whereKey($jobId)->update(['enabled' => $enabled]);

        return ['id' => $jobId, 'enabled' => $enabled];
    }

    /**
     * Strict 5-field cron, mirroring Python's `_validate_cron`.
     *
     * croniter also accepted 6- and 7-field forms, and so does
     * dragonmantank/cron-expression; the field count is checked separately so
     * a stored expression means the same thing to the scheduler as it did to
     * the crontab it replaced.
     */
    private static function cronError(string $expression): ?string
    {
        $trimmed = trim($expression);
        $fields = preg_split('/\s+/', $trimmed, -1, PREG_SPLIT_NO_EMPTY) ?: [];
        if (count($fields) !== 5 || !CronExpression::isValidExpression($trimmed)) {
            return 'Invalid cron expression: ' . self::pyRepr($expression)
                . ' (expected 5 fields)';
        }

        return null;
    }

    /** Walks the chain up from $chainToId looking for $jobId. */
    private static function wouldCycle(int $jobId, int $chainToId): bool
    {
        $visited = [];
        $next = $chainToId;
        while ($next !== null) {
            if ($next === $jobId) {
                return true;
            }
            if (isset($visited[$next])) {
                break;  // pre-existing cycle in the data — stop walking
            }
            $visited[$next] = true;
            $job = CronJob::find($next);
            if ($job === null) {
                break;
            }
            $next = $job->chain_to_job_id === null ? null : (int) $job->chain_to_job_id;
        }

        return false;
    }

    /** Python's `repr()` of a str, which is what the error message carries. */
    private static function pyRepr(string $value): string
    {
        if (!str_contains($value, "'")) {
            return "'" . str_replace('\\', '\\\\', $value) . "'";
        }
        if (!str_contains($value, '"')) {
            return '"' . str_replace('\\', '\\\\', $value) . '"';
        }

        return "'" . str_replace(['\\', "'"], ['\\\\', "\\'"], $value) . "'";
    }
}
