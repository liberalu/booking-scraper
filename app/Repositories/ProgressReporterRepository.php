<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ScrapeRun;
use Illuminate\Support\Carbon;

final class ProgressReporterRepository
{
    /** @param array<string, int> $tally */
    public function write(int $runId, int $processed, array $tally): void
    {
        ScrapeRun::whereKey($runId)->update([
            'urls_processed' => $processed,
            'items_added' => $tally['added'] ?? 0,
            'items_updated' => $tally['updated'] ?? 0,
            'error_count' => $tally['failed'] ?? 0,
            'last_heartbeat' => Carbon::now('UTC'),
        ]);
    }
}
