<?php

declare(strict_types=1);

use PhpCsFixer\Fixer\Import\NoUnusedImportsFixer;
use SlevomatCodingStandard\Sniffs\Namespaces\UselessAliasSniff;
use Symplify\EasyCodingStandard\Config\ECSConfig;

return ECSConfig::configure()
    ->withPaths([
        __DIR__.'/app',
        __DIR__.'/bootstrap',
        __DIR__.'/config',
        __DIR__.'/routes',
        __DIR__.'/tests',
        __FILE__,
        __DIR__.'/rector.php',
    ])
    ->withRules([
        NoUnusedImportsFixer::class,
        UselessAliasSniff::class,
    ]);
