<?php

declare(strict_types=1);

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

final class DashboardBasicAuth
{
    public function handle(Request $request, Closure $next): Response
    {
        $username = config('dashboard.username');
        $password = config('dashboard.password');
        if (! is_string($username) || $username === ''
            || ! is_string($password) || $password === '') {
            return $this->response($next($request));
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

    private function response(mixed $response): Response
    {
        if (! $response instanceof Response) {
            throw new \LogicException('Dashboard middleware received an invalid response');
        }

        return $response;
    }
}
