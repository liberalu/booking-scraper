<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Crawler\RunLifecycle;
use App\Repositories\CliRunRepository;
use App\Repositories\ShopRepository;
use App\Services\MatchService;
use App\Support\Database;
use Illuminate\Console\Command;
use Throwable;

final class MatchBooks extends Command
{
    protected $signature = 'books:match
        {--shop=vaga}
        {--synthesis}
        {--run-id=}
        {--database=}';

    protected $description = 'Link shop books to canonical books and backfill authors';

    public function __construct(
        private readonly MatchService $matching,
        private readonly ShopRepository $shops,
        private readonly CliRunRepository $runs,
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
        $runIdOption = $this->option('run-id');
        $runId = is_string($runIdOption) && ctype_digit($runIdOption)
            ? (int) $runIdOption
            : null;
        $lifecycle = $runId === null ? new RunLifecycle($shop->id, 'match') : null;
        $runId ??= $lifecycle?->start()->id;
        if ($runId === null) {
            $this->error('Could not create a match run');

            return self::FAILURE;
        }

        $synthesis = $this->option('synthesis') ? true : null;
        $this->line(sprintf(
            'match %s (run %d)%s',
            $shopName,
            $runId,
            $synthesis === true ? ' with synthesis' : '',
        ));

        try {
            $counters = $this->matching->run($shopName, $synthesis);
        } catch (Throwable $exception) {
            $lifecycle?->fail($exception);
            $this->error($exception->getMessage());

            return self::FAILURE;
        }

        foreach ($counters as $key => $count) {
            $this->line(sprintf('  %-20s %6d', $key, $count));
        }
        $this->runs->setItemsUpdated($runId, $counters['books_linked']);
        $lifecycle?->progress(
            processed: $counters['books_linked'],
            added: $counters['books_synthesized'],
            updated: $counters['books_linked'],
            errors: 0,
        );
        $lifecycle?->finish('completed');
        $this->info(sprintf(
            'done — %d linked, %d author link(s), %d synthesised',
            $counters['books_linked'],
            $counters['authors_linked'],
            $counters['books_synthesized'],
        ));

        return self::SUCCESS;
    }
}
