<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Crawler\RunLifecycle;
use App\Repositories\ShopRepository;
use App\Services\MatchService;
use App\Services\ValidateService;
use App\Support\Database;
use Illuminate\Console\Command;
use Throwable;

final class ValidateBooks extends Command
{
    protected $signature = 'books:validate
        {--shop=vaga}
        {--run-id=}
        {--match-first}
        {--database=}';

    protected $description = 'Run catalogue data-quality validation';

    public function __construct(
        private readonly ValidateService $validation,
        private readonly MatchService $matching,
        private readonly ShopRepository $shops,
    ) {
        parent::__construct();
    }

    public function handle(): int
    {
        $database = $this->option('database');
        if (is_string($database) && $database !== '') {
            Database::boot($database);
        }

        $shopName = (string) $this->option('shop');
        $shop = $this->shops->byName($shopName);
        if ($this->option('match-first')) {
            $linked = $this->matching->isbnMatch($shopName);
            $this->line(sprintf('match step 1: %d shop_book(s) linked by ISBN', $linked));
        }

        $runIdOption = $this->option('run-id');
        $runId = is_string($runIdOption) && ctype_digit($runIdOption)
            ? (int) $runIdOption
            : null;
        $lifecycle = $runId === null ? new RunLifecycle($shop->id, 'validate') : null;
        $runId ??= $lifecycle?->start()->id;
        if ($runId === null) {
            $this->error('Could not create a validation run');

            return self::FAILURE;
        }

        $this->line(sprintf('validate %s (run %d)', $shopName, $runId));
        try {
            $counters = $this->validation->run($shop->id, $runId);
        } catch (Throwable $exception) {
            $lifecycle?->fail($exception);
            $this->error($exception->getMessage());

            return self::FAILURE;
        }

        $total = array_sum($counters);
        foreach ($counters as $key => $count) {
            $this->line(sprintf('  %-26s %6d', $key, $count));
        }
        $this->info(sprintf('total %d issue(s)', $total));
        $lifecycle?->progress(processed: $total, added: 0, updated: 0, errors: 0);
        $lifecycle?->finish('completed');

        return self::SUCCESS;
    }
}
