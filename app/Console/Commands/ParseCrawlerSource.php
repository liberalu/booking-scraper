<?php

declare(strict_types=1);

namespace App\Console\Commands;

use App\Services\Crawler\CrawlerSourceParserService;
use Illuminate\Console\Command;
use JsonException;
use RuntimeException;

final class ParseCrawlerSource extends Command
{
    protected $signature = 'crawler:parse
        {--url=}
        {--file=}
        {--kind=}
        {--shop=vaga}
        {--ua=}';

    protected $description = 'Parse a live page, local file, or bundled fixture';

    public function __construct(private readonly CrawlerSourceParserService $parser)
    {
        parent::__construct();
    }

    public function handle(): int
    {
        try {
            $result = $this->parser->parse(
                (string) $this->option('shop'),
                $this->stringOption('url'),
                $this->stringOption('file'),
                $this->stringOption('kind'),
                $this->stringOption('ua'),
            );
            $this->output->writeln(json_encode(
                $result,
                JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR,
            ));
        } catch (RuntimeException|JsonException $exception) {
            $this->error($exception->getMessage());

            return self::FAILURE;
        }

        return self::SUCCESS;
    }

    private function stringOption(string $name): ?string
    {
        $value = $this->option($name);

        return is_string($value) && $value !== '' ? $value : null;
    }
}
