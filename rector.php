<?php

declare(strict_types=1);

use Rector\Config\RectorConfig;

return RectorConfig::configure()
    ->withPaths([
        __DIR__.'/app/DTO',
        __DIR__.'/app/Http/Controllers',
        __DIR__.'/app/Http/Requests',
        __DIR__.'/app/Queries',
        __DIR__.'/app/Services/Books',
        __DIR__.'/app/Services/Issues',
        __DIR__.'/app/Services/Legacy',
        __DIR__.'/app/Services/Runs',
        __DIR__.'/app/Services/Scheduling',
        __DIR__.'/app/Services/Shops',
    ])
    ->withPreparedSets(
        deadCode: true,
        codeQuality: true,
        typeDeclarations: true,
        earlyReturn: true,
    )
    ->withPhpSets(php84: true)
    ->withImportNames(removeUnusedImports: true);
