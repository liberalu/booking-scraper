<?php

declare(strict_types=1);

namespace App\Providers;

use App\Repositories\Contracts\CrawlerPersistenceRepositoryInterface;
use App\Repositories\Contracts\RunLifecycleRepositoryInterface;
use App\Repositories\Contracts\SchedulerRepositoryInterface;
use App\Repositories\CrawlerPersistenceRepository;
use App\Repositories\RunLifecycleRepository;
use App\Repositories\SchedulerRepository;
use Illuminate\Cache\RateLimiting\Limit;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\RateLimiter;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->app->bind(
            CrawlerPersistenceRepositoryInterface::class,
            CrawlerPersistenceRepository::class,
        );
        $this->app->bind(
            RunLifecycleRepositoryInterface::class,
            RunLifecycleRepository::class,
        );
        $this->app->bind(
            SchedulerRepositoryInterface::class,
            SchedulerRepository::class,
        );
    }

    public function boot(): void
    {

        RateLimiter::for('spawn', static fn (Request $request): Limit => Limit::perMinute(30)->by($request->ip() ?? 'unknown'));
    }
}
