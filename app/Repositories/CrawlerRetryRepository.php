<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Runs\RunEvent;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

final class CrawlerRetryRepository
{
    public function record(
        int $runId,
        string $url,
        int $attempt,
        ?int $httpStatus,
        ?string $error,
    ): void {
        DB::transaction(function () use ($runId, $url, $attempt, $httpStatus, $error): void {
            DB::table('scrape_url_items')
                ->where('run_id', $runId)
                ->where('url', $url)
                ->increment('retry_count');

            DB::table('scrape_run_events')->insert([
                'run_id' => $runId,
                'event_type' => RunEvent::REQUEST_RETRIED,
                'created_at' => Carbon::now('UTC'),
                'actor' => RunEvent::ACTOR_SYSTEM,
                'payload' => json_encode([
                    'url' => $url,
                    'attempt' => $attempt,
                    'http_status' => $httpStatus,
                    'error' => $error,
                ], JSON_THROW_ON_ERROR),
            ]);
        });
    }
}
