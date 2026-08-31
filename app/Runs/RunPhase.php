<?php

declare(strict_types=1);

namespace App\Runs;

enum RunPhase: string
{
    case Scan = 'scan';
    case Discover = 'discover';
    case Match = 'match';
    case Validate = 'validate';

    public function script(): string
    {
        return match ($this) {
            self::Scan, self::Discover => 'crawl',
            self::Match => 'match',
            self::Validate => 'validate',
        };
    }
}
