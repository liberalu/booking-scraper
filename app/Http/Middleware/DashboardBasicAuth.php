<?php

declare(strict_types=1);

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use LogicException;
use Symfony\Component\HttpFoundation\Response;

final class DashboardBasicAuth
{
    public function handle(Request $request, Closure $next): Response
    {
        if (config('dashboard.authentication_disabled') === true) {
            return $this->response($next($request));
        }

        $username = config('dashboard.username');
        $password = config('dashboard.password');
        if (! is_string($username) || $username === ''
            || ! is_string($password) || $password === '') {
            return $this->misconfigured($request);
        }

        if (hash_equals($username, (string) $request->getUser())
            && hash_equals($password, (string) $request->getPassword())) {
            return $this->response($next($request));
        }

        $headers = ['WWW-Authenticate' => 'Basic realm="Book Scraper"'];
        if ($request->is('api/*') || $request->expectsJson()) {
            return new JsonResponse(
                ['detail' => 'Authentication required'],
                Response::HTTP_UNAUTHORIZED,
                $headers,
            );
        }

        return new Response('Authentication required', Response::HTTP_UNAUTHORIZED, $headers);
    }

    private function misconfigured(Request $request): Response
    {
        if ($request->is('api/*') || $request->expectsJson()) {
            return new JsonResponse(
                ['detail' => 'Dashboard authentication is not configured'],
                Response::HTTP_SERVICE_UNAVAILABLE,
            );
        }

        return new Response(
            'Dashboard authentication is not configured',
            Response::HTTP_SERVICE_UNAVAILABLE,
        );
    }

    private function response(mixed $response): Response
    {
        if (! $response instanceof Response) {
            throw new LogicException('Dashboard middleware received an invalid response');
        }

        return $response;
    }
}
