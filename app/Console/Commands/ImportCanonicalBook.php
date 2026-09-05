<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Services\Books\CanonicalBookImportService;
use App\Support\Database;
use Illuminate\Console\Command;
use RuntimeException;

final class ImportCanonicalBook extends Command
{
    protected $signature = 'books:import-canonical
        {--url=}
        {--file=}
        {--database=}';

    protected $description = 'Import an iBiblioteka record into the canonical catalogue';

    public function __construct(private readonly CanonicalBookImportService $importer)
    {
        parent::__construct();
    }

    public function handle(): int
    {
        $url = $this->option('url');
        if (! is_string($url) || $url === '') {
            $this->error('--url is required');

            return self::INVALID;
        }

        $database = $this->option('database');
        if (is_string($database) && $database !== '') {
            Database::boot($database);
        }

        $file = $this->option('file');
        try {
            $book = $this->importer->import(
                $url,
                is_string($file) && $file !== '' ? $file : null,
            );
        } catch (RuntimeException $exception) {
            $this->error($exception->getMessage());

            return self::FAILURE;
        }
        $this->info(sprintf('books id=%d  %s', $book['id'], $book['title']));

        return self::SUCCESS;
    }
}
