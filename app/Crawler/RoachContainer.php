<?php

declare(strict_types=1);

namespace App\Crawler;

use App\Crawler\Scheduling\SubSecondClock;
use App\Crawler\Scheduling\SubSecondRequestScheduler;
use App\Repositories\CrawlerRetryRepository;
use GuzzleHttp\Client as GuzzleClient;
use GuzzleHttp\Exception\ConnectException;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Middleware;
use League\Container\Container as LeagueContainer;
use League\Container\ReflectionContainer;
use Monolog\Handler\StreamHandler;
use Monolog\Level;
use Monolog\Logger;
use Psr\Container\ContainerInterface;
use Psr\Http\Message\RequestInterface;
use Psr\Http\Message\ResponseInterface;
use Psr\Log\LoggerInterface;
use RoachPHP\Core\Engine;
use RoachPHP\Core\EngineInterface;
use RoachPHP\Core\Runner;
use RoachPHP\Core\RunnerInterface;
use RoachPHP\Http\Client as RoachClient;
use RoachPHP\Http\ClientInterface;
use RoachPHP\ItemPipeline\ItemPipeline;
use RoachPHP\ItemPipeline\ItemPipelineInterface;
use RoachPHP\Scheduling\RequestSchedulerInterface;
use RoachPHP\Scheduling\Timing\ClockInterface;
use Symfony\Component\EventDispatcher\EventDispatcher;
use Symfony\Component\EventDispatcher\EventDispatcherInterface;

final class RoachContainer implements ContainerInterface
{
    private readonly LeagueContainer $container;

    private readonly SubSecondRequestScheduler $scheduler;

    public function __construct(
        private readonly float $requestDelaySeconds,
        private readonly float $requestTimeout,
        private readonly float $connectTimeout,
        private readonly string $userAgent,
        private readonly ?int $runId = null,
        private readonly CrawlerRetryRepository $retries = new CrawlerRetryRepository,
        private readonly CrawlerContext $crawler = new CrawlerContext,
    ) {
        $this->container = (new LeagueContainer)->delegate(new ReflectionContainer);
        $this->scheduler = new SubSecondRequestScheduler(new SubSecondClock);
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
        $this->container->addShared(CrawlerContext::class, $this->crawler);
        $this->container->addShared(IssueBuffer::class, $this->crawler->issues());

        $configuredLevel = getenv('CRAWLER_LOG_LEVEL');
        $level = $this->logLevel(is_string($configuredLevel) ? $configuredLevel : 'warning');
        $this->container->addShared(
            LoggerInterface::class,
            static fn (): LoggerInterface => (new Logger('book-scraper'))
                ->pushHandler(new StreamHandler('php://stdout', $level)),
        );
        $this->container->addShared(EventDispatcher::class, EventDispatcher::class);
        $this->container->addShared(EventDispatcherInterface::class, EventDispatcher::class);

        $this->container->addShared(ClockInterface::class, fn (): ClockInterface => new SubSecondClock);
        $this->container->addShared(RequestSchedulerInterface::class, fn (): RequestSchedulerInterface => $this->scheduler);

        $this->container->addShared(
            ClientInterface::class,
            fn (): ClientInterface => new RecordingClient(
                new RoachClient($this->httpClient()),
                $this->crawler->issues(),
            ),
        );

        $this->container->add(
            ItemPipelineInterface::class,
            fn (): ItemPipelineInterface => $this->itemPipeline(),
        );
        $this->container->add(
            EngineInterface::class,
            fn (): EngineInterface => $this->engine(),
        );
        $this->container->add(
            RunnerInterface::class,
            fn (): RunnerInterface => new Runner(
                $this->container,
                $this->engine(),
            ),
        );
    }

    private function httpClient(): GuzzleClient
    {
        $stack = HandlerStack::create();
        $stack->push(Middleware::retry(
            function (
                int $retries,
                RequestInterface $request,
                ?ResponseInterface $response,
                ?\Throwable $exception,
            ): bool {
                $retry = $retries < 2 && (
                    $exception instanceof ConnectException
                    || $response?->getStatusCode() === 429
                    || ($response !== null && $response->getStatusCode() >= 500)
                );
                if ($retry && $this->runId !== null) {
                    $this->retries->record(
                        $this->runId,
                        (string) $request->getUri(),
                        $retries + 1,
                        $response?->getStatusCode(),
                        $exception?->getMessage(),
                    );
                }

                return $retry;
            },
            static fn (int $retries): int => 500 * (2 ** max(0, $retries - 1)),
        ));

        return new GuzzleClient([
            'handler' => $stack,
            'timeout' => $this->requestTimeout,
            'connect_timeout' => $this->connectTimeout,
            'headers' => ['User-Agent' => $this->userAgent],
        ]);
    }

    private function itemPipeline(): ItemPipelineInterface
    {
        $pipeline = $this->container->get(ItemPipeline::class);
        if (! $pipeline instanceof ItemPipelineInterface) {
            throw new \RuntimeException('Roach item pipeline binding is invalid.');
        }

        return $pipeline;
    }

    private function engine(): EngineInterface
    {
        $engine = $this->container->get(Engine::class);
        if (! $engine instanceof EngineInterface) {
            throw new \RuntimeException('Roach engine binding is invalid.');
        }

        return $engine;
    }

    private function logLevel(string $value): Level
    {
        return match (strtolower($value)) {
            'debug' => Level::Debug,
            'info' => Level::Info,
            'notice' => Level::Notice,
            'warning' => Level::Warning,
            'error' => Level::Error,
            'critical' => Level::Critical,
            'alert' => Level::Alert,
            'emergency' => Level::Emergency,
            default => Level::Warning,
        };
    }
}
