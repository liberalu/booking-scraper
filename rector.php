<?php

declare(strict_types=1);

use Rector\Config\RectorConfig;
use RectorLaravel\Set\LaravelSetList;

return RectorConfig::configure()
    ->withPaths([
        __DIR__.'/app',
        __DIR__.'/bootstrap',
        __DIR__.'/config',
        __DIR__.'/routes',
        __DIR__.'/tests',
    ])
    ->withPreparedSets(
        deadCode: true,
        codeQuality: true,
        typeDeclarations: true,
        earlyReturn: true,
    )
    ->withPhpSets(php84: true)
    ->withSets([LaravelSetList::LARAVEL_CODE_QUALITY])
    ->withSkip([
        __DIR__.'/bootstrap/cache',
    ])
    ->withImportNames(removeUnusedImports: true);
