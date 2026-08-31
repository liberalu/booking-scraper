<?php

declare(strict_types=1);

namespace App\Repositories;

use App\Models\ScrapeRun;

final class CliRunRepository
{
    public function setItemsUpdated(int $runId, int $count): void
    {
        ScrapeRun::whereKey($runId)->update(['items_updated' => $count]);
    }
}
