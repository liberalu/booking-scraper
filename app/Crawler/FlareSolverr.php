<?php

declare(strict_types=1);

namespace App\Crawler;

use GuzzleHttp\Client;
use GuzzleHttp\Exception\GuzzleException;
use RuntimeException;

/** @phpstan-import-type FlareResponse from CrawlerTypes */
final class FlareSolverr
{
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

        $this->client = $client ?? new Client([
            'timeout' => ($maxTimeoutMs / 1000) + 30,
            'connect_timeout' => 10,
        ]);
    }

    /** @return FlareResponse */
    public function get(string $url): array
    {
        return $this->request('request.get', $url);
    }

    /** @return FlareResponse */
    public function post(string $url, string $postData): array
    {
        return $this->request('request.post', $url, $postData);
    }

    /** @return FlareResponse */
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

            $rawMessage = $data['message'] ?? null;
            $message = is_string($rawMessage) ? $rawMessage : 'FlareSolverr error';

            return [
                'status' => 502,
                'body' => $message,
                'url' => $url,
                'headers' => ['X-FlareSolverr-Error' => $message],
            ];
        }

        $rawSolution = $data['solution'] ?? null;
        $solution = is_array($rawSolution) ? $rawSolution : [];

        return [
            'status' => self::integer($solution['status'] ?? null, 200),
            'body' => self::string($solution['response'] ?? null, ''),
            'url' => self::string($solution['url'] ?? null, $url),
            'headers' => self::normaliseHeaders($solution['headers'] ?? null),
        ];
    }

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

                $this->destroySession($old);

                return $new;
            }

            $this->destroySession($this->sessionId);
        }

        return $this->createSession($now);
    }

    private function createSession(float $now): string
    {
        $data = $this->call(['cmd' => 'sessions.create']);
        $session = $data['session'] ?? null;
        if (! is_string($session) || $session === '') {
            throw new RuntimeException('FlareSolverr sessions.create returned no session id');
        }

        $this->sessionId = $session;
        $this->sessionStartedAt = $now;
        fwrite(STDERR, "  flaresolverr: session {$session}\n");

        return $session;
    }

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
                'FlareSolverr request failed: '.$e->getMessage(),
                previous: $e
            );
        }

        $decoded = json_decode((string) $response->getBody(), true);
        if (! is_array($decoded)) {
            throw new RuntimeException('FlareSolverr returned a non-JSON body');
        }

        $object = [];
        foreach ($decoded as $key => $value) {
            if (is_string($key)) {
                $object[$key] = $value;
            }
        }

        return $object;
    }

    /** @return array<string, string> */
    private static function normaliseHeaders(mixed $raw): array
    {
        if (! is_array($raw)) {
            return [];
        }

        $headers = [];
        foreach ($raw as $header) {
            if (! is_array($header)) {
                continue;
            }
            $name = self::string($header['name'] ?? null, '');
            $name = trim($name);
            if ($name === '' || strtolower($name) === 'content-encoding') {
                continue;
            }
            $headers[$name] = self::string($header['value'] ?? null, '');
        }

        return $headers;
    }

    private static function string(mixed $value, string $default): string
    {
        return is_string($value) ? $value : $default;
    }

    private static function integer(mixed $value, int $default): int
    {
        if (is_int($value)) {
            return $value;
        }
        if (is_string($value) && ctype_digit($value)) {
            return (int) $value;
        }

        return $default;
    }
}
