<?php

declare(strict_types=1);

namespace App\Crawler;

use GuzzleHttp\Client;
use GuzzleHttp\Exception\GuzzleException;
use RuntimeException;

/**
 * Fetches pages through a FlareSolverr sidecar, ported from
 * book_scraper/flaresolverr_middleware.py.
 *
 * humanitas puts a Cloudflare Managed Challenge on every URL, so plain
 * requests are useless there. FlareSolverr drives a real Chromium, solves
 * the challenge and returns the rendered HTML.
 *
 * Sessions are reused so the `cf_clearance` cookie sticks — FlareSolverr
 * keeps the cookie jar attached to the session. Cloudflare's wall is ~30
 * minutes, so the session is rotated before that (`session_ttl_minutes`).
 *
 * CONCURRENCY MUST BE 1. The middleware reuses a single browser session
 * across requests, and two concurrent `request.get` calls on one session
 * race for the same browser instance — the second response silently returns
 * the FIRST request's body. That produced the 2026-05-22 humanitas
 * regression where one product's metadata was written to another's row.
 */
final class FlareSolverr
{
    /**
     * Mint the replacement session this many seconds before the current one
     * expires. Creating one costs a challenge solve (~10–15s), so it needs
     * to be ready before the old session stops being trusted.
     */
    private const PRE_ROTATION_BUFFER_S = 90.0;

    private ?string $sessionId = null;

    private float $sessionStartedAt = 0.0;

    private readonly Client $client;

    private readonly int $sessionTtlSeconds;

    public function __construct(
        private readonly string $endpoint,
        private readonly int $maxTimeoutMs = 120_000,
        int $sessionTtlMinutes = 25,
        ?Client $client = null,
    ) {
        $this->sessionTtlSeconds = $sessionTtlMinutes * 60;
        // The HTTP timeout must exceed FlareSolverr's own, or a challenge
        // solve that is merely slow looks like a transport failure.
        $this->client = $client ?? new Client([
            'timeout' => ($maxTimeoutMs / 1000) + 30,
            'connect_timeout' => 10,
        ]);
    }

    /**
     * Fetch a URL through FlareSolverr.
     *
     * @return array{status: int, body: string, url: string, headers: array<string, string>}
     */
    public function get(string $url): array
    {
        return $this->request('request.get', $url);
    }

    /** @return array{status: int, body: string, url: string, headers: array<string, string>} */
    public function post(string $url, string $postData): array
    {
        return $this->request('request.post', $url, $postData);
    }

    /** @return array{status: int, body: string, url: string, headers: array<string, string>} */
    private function request(string $cmd, string $url, ?string $postData = null): array
    {
        $body = [
            'cmd' => $cmd,
            'url' => $url,
            'session' => $this->ensureSession(),
            'maxTimeout' => $this->maxTimeoutMs,
        ];
        if ($postData !== null) {
            $body['postData'] = $postData;
        }

        $data = $this->call($body);

        if (($data['status'] ?? null) !== 'ok') {
            // FlareSolverr itself failed — unsolvable challenge, browser
            // crash. Surfaced as a 502 so the retry path handles it rather
            // than the caller treating an error page as content.
            $message = (string) ($data['message'] ?? 'FlareSolverr error');

            return [
                'status' => 502,
                'body' => $message,
                'url' => $url,
                'headers' => ['X-FlareSolverr-Error' => $message],
            ];
        }

        $solution = $data['solution'] ?? [];

        return [
            'status' => (int) ($solution['status'] ?? 200),
            'body' => (string) ($solution['response'] ?? ''),
            'url' => (string) ($solution['url'] ?? $url),
            'headers' => self::normaliseHeaders($solution['headers'] ?? null),
        ];
    }

    /**
     * A usable session id, rotated ahead of TTL.
     *
     * Three paths: healthy (well inside TTL), pre-rotation (inside the
     * buffer — mint a replacement but keep serving the old id until the new
     * one is ready, so only the triggering request pays the cost), and hard
     * expiry (past TTL, destroy before creating because the old session
     * can no longer be trusted).
     */
    public function ensureSession(): string
    {
        $now = microtime(true);

        if ($this->sessionId !== null) {
            $age = $now - $this->sessionStartedAt;

            if ($age < $this->sessionTtlSeconds - self::PRE_ROTATION_BUFFER_S) {
                return $this->sessionId;
            }

            if ($age < $this->sessionTtlSeconds) {
                $old = $this->sessionId;
                try {
                    $new = $this->createSession($now);
                } catch (\Throwable $e) {
                    fwrite(STDERR, "  flaresolverr: pre-rotation failed, staying on the old session\n");

                    return $old;
                }
                // Destroyed only after the swap, so a request still in flight
                // on the old session can finish.
                $this->destroySession($old);

                return $new;
            }

            // Past TTL: destroy first, the cookie is no longer trusted.
            $this->destroySession($this->sessionId);
        }

        return $this->createSession($now);
    }

    private function createSession(float $now): string
    {
        $data = $this->call(['cmd' => 'sessions.create']);
        $session = $data['session'] ?? null;
        if (!is_string($session) || $session === '') {
            throw new RuntimeException('FlareSolverr sessions.create returned no session id');
        }

        $this->sessionId = $session;
        $this->sessionStartedAt = $now;
        fwrite(STDERR, "  flaresolverr: session {$session}\n");

        return $session;
    }

    /** Best-effort: a failed teardown must not block the caller. */
    private function destroySession(string $session): void
    {
        try {
            $this->call(['cmd' => 'sessions.destroy', 'session' => $session]);
        } catch (\Throwable $e) {
            fwrite(STDERR, "  flaresolverr: destroy of session {$session} failed (continuing)\n");
        }
    }

    public function close(): void
    {
        if ($this->sessionId !== null) {
            $this->destroySession($this->sessionId);
            $this->sessionId = null;
        }
    }

    /**
     * @param  array<string, mixed>  $body
     * @return array<string, mixed>
     */
    private function call(array $body): array
    {
        try {
            $response = $this->client->post($this->endpoint, ['json' => $body]);
        } catch (GuzzleException $e) {
            throw new RuntimeException(
                'FlareSolverr request failed: ' . $e->getMessage(),
                previous: $e
            );
        }

        $decoded = json_decode((string) $response->getBody(), true);
        if (!is_array($decoded)) {
            throw new RuntimeException('FlareSolverr returned a non-JSON body');
        }

        return $decoded;
    }

    /**
     * Headers arrive as a list of {name, value}.
     *
     * Content-Encoding is dropped: FlareSolverr already returns decoded
     * HTML, and leaving the header on makes a downstream client try to
     * decompress plain text.
     *
     * @return array<string, string>
     */
    private static function normaliseHeaders(mixed $raw): array
    {
        if (!is_array($raw)) {
            return [];
        }

        $headers = [];
        foreach ($raw as $header) {
            if (!is_array($header)) {
                continue;
            }
            $name = trim((string) ($header['name'] ?? ''));
            if ($name === '' || strtolower($name) === 'content-encoding') {
                continue;
            }
            $headers[$name] = (string) ($header['value'] ?? '');
        }

        return $headers;
    }
}
