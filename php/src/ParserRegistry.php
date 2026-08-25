<?php

declare(strict_types=1);

namespace BookScraper;

use RuntimeException;

/**
 * Resolves a shop name to its parser class, mirroring
 * book_scraper/spiders/registry.py.
 *
 * The Python version imports `book_scraper.spiders.<shop>.parsers`
 * dynamically. An explicit map is used here instead: a typo'd shop name
 * fails with a list of what exists rather than a bare ImportError, and the
 * set of supported shops stays greppable.
 */
final class ParserRegistry
{
    /** @var array<string, class-string> */
    private const PARSERS = [
        'vaga' => Vaga\Parser::class,
        'pegasas' => Pegasas\Parser::class,
        'patogupirkti' => Patogupirkti\Parser::class,
        'humanitas' => Humanitas\Parser::class,
        'almalittera' => Almalittera\Parser::class,
        'ibiblioteka' => Ibiblioteka\Parser::class,
    ];

    /** @return class-string */
    public static function for(string $shop): string
    {
        $parser = self::PARSERS[$shop] ?? null;
        if ($parser === null) {
            throw new RuntimeException(sprintf(
                'no parser for shop "%s" — known shops: %s',
                $shop,
                implode(', ', array_keys(self::PARSERS))
            ));
        }

        return $parser;
    }

    public static function has(string $shop): bool
    {
        return isset(self::PARSERS[$shop]);
    }

    /** @return list<string> */
    public static function shops(): array
    {
        return array_keys(self::PARSERS);
    }

    /**
     * True when the shop's parser implements the given entry point.
     *
     * Not every shop supports every strategy — pegasas has no sitemap,
     * ibiblioteka has no category HTML — so callers check before dispatching
     * rather than relying on an exception.
     */
    public static function supports(string $shop, string $method): bool
    {
        return self::has($shop) && method_exists(self::for($shop), $method);
    }
}
