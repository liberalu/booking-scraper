<?php

use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Foundation\Configuration\Middleware;
use Illuminate\Http\Request;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        web: __DIR__.'/../routes/web.php',
        commands: __DIR__.'/../routes/console.php',
        health: '/up',
    )
    ->withMiddleware(function (Middleware $middleware): void {
        // The API is called by the SPA's fetch(), which sends no CSRF token —
        // the Python dashboard it replaces has no CSRF layer at all, so
        // requiring one here would break every mutation. The /scrape and
        // rate-settings form posts predate the SPA and are in the same
        // position.
        $middleware->validateCsrfTokens(except: [
            'api/*',
            'scrape/*',
            'shops/*/rate-settings',
        ]);
    })
    ->withExceptions(function (Exceptions $exceptions): void {
        $exceptions->shouldRenderJsonWhen(
            fn (Request $request) => $request->is('api/*') || $request->expectsJson(),
        );
    })->create();
