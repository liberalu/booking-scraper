<?php

declare(strict_types=1);

namespace Tests\Unit;

use App\Support\Config;
use PHPUnit\Framework\TestCase;

final class ConfigTest extends TestCase
{
    public function test_category_strategy_accepts_one_or_many_url_templates(): void
    {
        self::assertCount(1, Config::forShop('vaga')->strategyUrls('categories'));
        self::assertCount(2, Config::forShop('humanitas')->strategyUrls('categories'));
        self::assertCount(3, Config::forShop('patogupirkti')->strategyUrls('categories'));
    }
}
