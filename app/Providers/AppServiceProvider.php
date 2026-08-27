<?php

declare(strict_types=1);

namespace App\Providers;

use Illuminate\Cache\RateLimiting\Limit;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\RateLimiter;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    /**
     * Register any application services.
     */
    public function register(): void
    {
        //
    }

    /**
     * Bootstrap any application services.
     */
    public function boot(): void
    {
        /**
         * The routes that start a crawl.
         *
         * Two groups reach `CrawlSpawner::spawn()`: the four
         * `RunSpawnController` routes under /api, and the three pre-SPA
         * `/scrape/*` form posts, which are web routes and CSRF-exempt. They
         * share one limiter because they share one consequence — a process
         * fetching a live bookshop — and because a cap written twice drifts.
         *
         * 30/minute is far above what an operator clicking buttons produces
         * and far below what a loop produces. It bounds the damage from a
         * runaway client; it is not authentication. See docs/follow-ups.md.
         */
        RateLimiter::for('spawn', static fn (Request $request): Limit
            => Limit::perMinute(30)->by($request->ip() ?? 'unknown'));
    }
}
