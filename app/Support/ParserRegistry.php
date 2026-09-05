<?php

declare(strict_types=1);

namespace App\Support;

use App\Parsers\ProductParser;
use App\Parsers\Vaga\Parser;
use RuntimeException;

final class ParserRegistry
{
    private const array PARSERS = [
        'vaga' => Parser::class,
        'pegasas' => \App\Parsers\Pegasas\Parser::class,
        'patogupirkti' => \App\Parsers\Patogupirkti\Parser::class,
        'humanitas' => \App\Parsers\Humanitas\Parser::class,
        'almalittera' => \App\Parsers\Almalittera\Parser::class,
        'ibiblioteka' => \App\Parsers\Ibiblioteka\Parser::class,
    ];

    /** @return class-string<ProductParser> */
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

    public static function supports(string $shop, string $method): bool
    {
        return self::has($shop) && method_exists(self::for($shop), $method);
    }
}
