<?php

declare(strict_types=1);

namespace BookScraper\Crawler;

use BookScraper\Crawler\Scheduling\SubSecondClock;
use BookScraper\Crawler\Scheduling\SubSecondRequestScheduler;
use GuzzleHttp\Client as GuzzleClient;
use RoachPHP\Http\Client as RoachClient;
use RoachPHP\Http\ClientInterface;
use League\Container\Container as LeagueContainer;
use League\Container\ReflectionContainer;
use Monolog\Handler\StreamHandler;
use Monolog\Level;
use Monolog\Logger;
use Psr\Container\ContainerInterface;
use Psr\Log\LoggerInterface;
use RoachPHP\Core\Engine;
use RoachPHP\Core\EngineInterface;
use RoachPHP\Core\Runner;
use RoachPHP\Core\RunnerInterface;
use RoachPHP\ItemPipeline\ItemPipeline;
use RoachPHP\ItemPipeline\ItemPipelineInterface;
use RoachPHP\Scheduling\RequestSchedulerInterface;
use RoachPHP\Scheduling\Timing\ClockInterface;
use Symfony\Component\EventDispatcher\EventDispatcher;
use Symfony\Component\EventDispatcher\EventDispatcherInterface;

/**
 * Roach's own DefaultContainer is `final` and `@internal`, so swapping the
 * scheduler means providing a container rather than extending theirs.
 *
 * The only substantive changes are the scheduler and clock: both defaults
 * truncate the request delay to whole seconds, which five of six shops pace
 * below (see Scheduling\SubSecondRequestScheduler).
 */
final class RoachContainer implements ContainerInterface
{
    private readonly LeagueContainer $container;

    private readonly SubSecondRequestScheduler $scheduler;

    public function __construct(
        private readonly float $requestDelaySeconds,
        private readonly float $requestTimeout,
        private readonly float $connectTimeout,
        private readonly string $userAgent,
    ) {
        $this->container = (new LeagueContainer())->delegate(new ReflectionContainer());
        $this->scheduler = new SubSecondRequestScheduler(new SubSecondClock());
        $this->scheduler->setDelaySeconds($this->requestDelaySeconds);

        $this->registerBindings();
    }

    public function get(string $id): mixed
    {
        return $this->container->get($id);
    }

    public function has(string $id): bool
    {
        return $this->container->has($id);
    }

    public function scheduler(): SubSecondRequestScheduler
    {
        return $this->scheduler;
    }

    private function registerBindings(): void
    {
        $this->container->addShared(ContainerInterface::class, $this->container);
        // WARNING, not INFO: roach's LoggerExtension logs each scraped item
        // in full, and a book's description alone is a screenful. The CLI
        // prints its own progress summary instead. Raise with
        // CRAWLER_LOG_LEVEL=info when debugging a run.
        $level = Level::fromName(getenv('CRAWLER_LOG_LEVEL') ?: 'warning');
        $this->container->addShared(
            LoggerInterface::class,
            static fn (): LoggerInterface => (new Logger('book-scraper'))
                ->pushHandler(new StreamHandler('php://stdout', $level)),
        );
        $this->container->addShared(EventDispatcher::class, EventDispatcher::class);
        $this->container->addShared(EventDispatcherInterface::class, EventDispatcher::class);

        // The two swapped bindings.
        $this->container->addShared(ClockInterface::class, fn (): ClockInterface => new SubSecondClock());
        $this->container->addShared(RequestSchedulerInterface::class, fn (): RequestSchedulerInterface => $this->scheduler);

        // roach's own Http\ClientInterface, wrapping a Guzzle client that
        // carries the shop's timeouts. The UA matches what the Python
        // crawler sends — a different UA can get different HTML.
        $this->container->addShared(
            ClientInterface::class,
            // Wrapped so one unreachable URL is recorded and skipped rather
            // than aborting the run — see RecordingClient.
            fn (): ClientInterface => new RecordingClient(new RoachClient(new GuzzleClient([
                'timeout' => $this->requestTimeout,
                'connect_timeout' => $this->connectTimeout,
                'headers' => ['User-Agent' => $this->userAgent],
            ]))),
        );

        $this->container->add(
            ItemPipelineInterface::class,
            fn (): ItemPipelineInterface => $this->container->get(ItemPipeline::class),
        );
        $this->container->add(
            EngineInterface::class,
            fn (): EngineInterface => $this->container->get(Engine::class),
        );
        $this->container->add(
            RunnerInterface::class,
            fn (): RunnerInterface => new Runner(
                $this->container,
                $this->container->get(EngineInterface::class),
            ),
        );
    }
}
