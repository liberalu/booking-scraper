<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Runs\RunEvent;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

final class RunFinisherRepository
{
    private const NON_TERMINAL = ['running', 'stopping', 'paused'];

    public function __construct(
        private readonly RunFailsafeRepository $failsafe = new RunFailsafeRepository,
    ) {}

    public function finish(
        int $runId,
        string $status,
        ?string $reason = null,
        bool $resumableAfterFailure = false,
    ): bool {
        return DB::transaction(function () use (
            $runId,
            $status,
            $reason,
            $resumableAfterFailure
        ): bool {
            $run = DB::table('scrape_runs')->where('id', $runId)->lockForUpdate()->first();
            if ($run === null) {
                return false;
            }

            $row = DatabaseRow::from($run);
            $wasNonTerminal = in_array($row->string('status'), self::NON_TERMINAL, true);

            $fields = [
                'status' => $status,
                'finished_at' => Carbon::now('UTC'),
            ];

            if ($reason !== null && $row->nullableString('close_reason') === null) {
                $fields['close_reason'] = $reason;
            }
            if ($resumableAfterFailure) {
                $fields['resumable_after_failure'] = true;
            }
            DB::table('scrape_runs')->where('id', $runId)->update($fields);

            if (! $wasNonTerminal) {
                return true;
            }

            $this->abortProcessingItems($runId);
            if ($status === 'failed') {
                $this->recordFailureIssue($runId, $row->int('shop_id'), $reason ?? 'finished_failed');
            }
            if (in_array($status, ['completed', 'failed'], true)) {
                $fresh = DB::table('scrape_runs')->where('id', $runId)->first();
                $freshRow = DatabaseRow::nullable($fresh);
                $this->failsafe->recordEvent(
                    $runId,
                    $status === 'completed' ? RunEvent::COMPLETED : RunEvent::FAILED,
                    [
                        'close_reason' => $freshRow?->nullableString('close_reason'),
                        'urls_processed' => $freshRow?->nullableInt('urls_processed') ?? 0,
                        'error_count' => $freshRow?->nullableInt('error_count') ?? 0,
                    ],
                );
            }

            return true;
        });
    }

    public function abortProcessingItems(int $runId): int
    {
        $items = DB::table('scrape_url_items')
            ->where('run_id', $runId)
            ->where('status', 'processing')
            ->whereNull('done_at')
            ->get(['id', 'run_id', 'shop_id', 'url', 'discovered_url_id']);
        if ($items->isEmpty()) {
            return 0;
        }

        $now = Carbon::now('UTC');
        DB::table('scrape_url_items')
            ->whereIn('id', $items->pluck('id')->all())
            ->update(['status' => 'failed', 'done_at' => $now]);

        DB::table('scrape_failures')->insert($items->map(
            static fn ($item): array => [
                'scrape_url_item_id' => $item->id,
                'run_id' => $item->run_id,
                'shop_id' => $item->shop_id,
                'url' => $item->url,
                'discovered_url_id' => $item->discovered_url_id,
                'occurred_at' => $now,
                'error_reason' => 'run_aborted',
                'http_status' => null,
                'error_detail' => 'run_aborted',
                'lifecycle_state' => 'new',
            ]
        )->all());

        return $items->count();
    }

    private function recordFailureIssue(int $runId, int $shopId, string $reason): void
    {
        $existing = DB::table('validation_issues')
            ->where('last_seen_run_id', $runId)
            ->where('issue', 'scrape_run_failed')
            ->exists();
        if ($existing) {
            return;
        }
        DB::table('validation_issues')->insert([
            'last_seen_run_id' => $runId,
            'shop_id' => $shopId,
            'url' => "run:{$runId}",
            'field' => 'run',
            'issue' => 'scrape_run_failed',
            'raw_value' => $reason,
            'lifecycle_state' => 'new',
            'run_count' => 1,
        ]);
    }
}
