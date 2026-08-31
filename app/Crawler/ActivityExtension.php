<?php

declare(strict_types=1);

namespace App\Crawler;

use RoachPHP\Events\ItemScraped;
use RoachPHP\Events\RequestDropped;
use RoachPHP\Events\RequestSending;
use RoachPHP\Events\ResponseReceived;
use RoachPHP\Extensions\ExtensionInterface;
use RoachPHP\Support\Configurable;

final class ActivityExtension implements ExtensionInterface
{
    use Configurable;

    public function __construct(private readonly CrawlerContext $context = new CrawlerContext) {}

    public static function getSubscribedEvents(): array
    {
        return [
            ResponseReceived::NAME => ['onActivity', 0],
            ItemScraped::NAME => ['onActivity', 0],
            RequestSending::NAME => ['onActivity', 0],
            RequestDropped::NAME => ['onActivity', 0],
        ];
    }

    public function onActivity(object $event): void
    {
        $this->context->recordActivity();
    }
}
