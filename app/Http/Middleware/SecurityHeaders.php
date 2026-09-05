<?php

declare(strict_types=1);

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use LogicException;
use Symfony\Component\HttpFoundation\Response;

final class SecurityHeaders
{
    public function handle(Request $request, Closure $next): Response
    {
        $response = $next($request);
        if (! $response instanceof Response) {
            throw new LogicException('Security middleware received an invalid response');
        }

        $response->headers->set('X-Content-Type-Options', 'nosniff');
        $response->headers->set('X-Frame-Options', 'DENY');
        $response->headers->set('Referrer-Policy', 'same-origin');
        $response->headers->set('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
        $scriptSources = config('app.env') === 'production'
            ? "script-src 'self' 'unsafe-inline'"
            : "script-src 'self' 'unsafe-inline' https://unpkg.com";
        $response->headers->set(
            'Content-Security-Policy',
            "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; "
            ."img-src 'self' data: https:; font-src 'self' https://fonts.gstatic.com; "
            ."style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            ."{$scriptSources}; connect-src 'self'",
        );

        if ($request->is('api/*') || $request->user() !== null || $request->getUser() !== null) {
            $response->headers->set('Cache-Control', 'no-store, private');
        }

        return $response;
    }
}
