<?php

use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Foundation\Configuration\Middleware;
use Illuminate\Http\Request;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        web: __DIR__.'/../routes/web.php',
        api: __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
        health: '/up',
    )
    ->withMiddleware(function (Middleware $middleware): void {
        // routes/api.php carries the `api` middleware group, which has no CSRF
        // layer, so /api/* needs no exemption here. These two do: they are web
        // routes, and the pre-SPA forms that post to them send no token — the
        // Python dashboard they replace had no CSRF layer at all.
        $middleware->validateCsrfTokens(except: [
            'scrape/*',
            'shops/*/rate-settings',
        ]);
    })
    ->withExceptions(function (Exceptions $exceptions): void {
        $exceptions->shouldRenderJsonWhen(
            fn (Request $request) => $request->is('api/*') || $request->expectsJson(),
        );
    })->create();
