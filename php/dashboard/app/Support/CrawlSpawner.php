<?php

declare(strict_types=1);

namespace App\Support;

use RuntimeException;

/**
 * Fire-and-forget a crawl.
 *
 * The Python dashboard runs in its own container and reaches the scraper via
 * `docker exec`; this one runs beside the crawler, so it spawns it directly.
 * Either way the contract is the same: the process is detached, its output
 * goes to a per-spawn log file so a silent crash leaves a trail, and the
 * caller does not wait for it.
 *
 * The database is passed explicitly rather than inherited, so a dashboard
 * pointed at the test database can only ever spawn a crawl against the test
 * database.
 */
final class CrawlSpawner
{
    /**
     * @return array{log: string, pid: int|null, cmd: list<string>}
     */
    public static function spawn(
        string $phase,
        string $shop,
        string $strategy = '',
        string $mode = 'delta',
        string $urls = '',
        ?int $cronJobId = null,
        string $role = 'operator',
    ): array {
        $binary = self::phpBinary();
        $script = self::crawlScript();

        $cmd = [$binary, $script, $phase, "--shop={$shop}"];
        if ($phase === 'discover' && $strategy !== '') {
            $cmd[] = "--strategy={$strategy}";
        }
        if ($phase === 'scan') {
            if ($urls !== '') {
                $cmd[] = "--urls={$urls}";
            } elseif ($mode === 'full') {
                $cmd[] = '--mode=full';
                $cmd[] = '--max-urls=0';
            } elseif ($mode === 'sample') {
                $cmd[] = '--max-urls=10';
            } else {
                $cmd[] = '--max-urls=0';
            }
        }
        if ($cronJobId !== null) {
            $cmd[] = "--cron-job-id={$cronJobId}";
        }
        $cmd[] = '--database=' . self::databaseUrl();

        // The role reaches Loki as a label (operator / cron / stall-resume /
        // …) by way of the filename, so a scheduled crawl is distinguishable
        // from one someone clicked.
        $log = self::logPath($role, $shop);
        $pid = self::detach($cmd, $log);

        return ['log' => $log, 'pid' => $pid, 'cmd' => $cmd];
    }

    /** Where a spawn's stdout+stderr lands. */
    public static function logDir(): string
    {
        $dir = getenv('SPAWN_LOG_DIR');

        return is_string($dir) && $dir !== '' ? $dir : storage_path('logs/spawn');
    }

    private static function logPath(string $role, string $shop): string
    {
        // Same shape as compute_spawn_log_path() so both stacks' logs sort
        // together in one directory listing.
        $stamp = (new \DateTimeImmutable('now', new \DateTimeZone('UTC')))
            ->format('Ymd-Hisu');

        return sprintf(
            '%s/spawn-%s-%s-%s.log',
            rtrim(self::logDir(), '/'),
            $stamp,
            self::slug($role),
            self::slug($shop)
        );
    }

    private static function slug(string $value): string
    {
        $slug = preg_replace('/[^A-Za-z0-9._-]+/', '-', $value) ?? $value;

        return trim($slug, '-') ?: 'unknown';
    }

    /**
     * `nohup … &` rather than a plain child: the shell exits at once and the
     * crawl is re-parented, so it survives the request finishing.
     *
     * @param list<string> $cmd
     */
    private static function detach(array $cmd, string $log): ?int
    {
        $quoted = implode(' ', array_map('escapeshellarg', $cmd));
        $script = sprintf(
            'mkdir -p %s && nohup %s >> %s 2>&1 & echo $!',
            escapeshellarg(dirname($log)),
            $quoted,
            escapeshellarg($log)
        );

        $descriptors = [1 => ['pipe', 'w'], 2 => ['pipe', 'w']];
        $process = @proc_open(['/bin/sh', '-c', $script], $descriptors, $pipes);
        if (!is_resource($process)) {
            throw new RuntimeException('Could not spawn a crawl process');
        }
        $out = trim((string) stream_get_contents($pipes[1]));
        $err = trim((string) stream_get_contents($pipes[2]));
        foreach ($pipes as $pipe) {
            fclose($pipe);
        }
        $status = proc_close($process);
        if ($status !== 0) {
            throw new RuntimeException(
                'Crawl spawn failed' . ($err !== '' ? ": {$err}" : '')
            );
        }

        return ctype_digit($out) ? (int) $out : null;
    }

    /** The 8.4 runtime the crawler needs — roach-php does not support 8.5. */
    private static function phpBinary(): string
    {
        $configured = getenv('CRAWLER_PHP_BINARY');
        if (is_string($configured) && $configured !== '' && is_executable($configured)) {
            return $configured;
        }
        foreach (['/opt/homebrew/opt/php@8.4/bin/php', PHP_BINARY] as $candidate) {
            if (is_string($candidate) && $candidate !== '' && is_executable($candidate)) {
                return $candidate;
            }
        }

        throw new RuntimeException('No PHP binary available to spawn the crawler');
    }

    private static function crawlScript(): string
    {
        $script = dirname(base_path()) . '/crawler/bin/crawl';
        if (!is_file($script)) {
            throw new RuntimeException("Crawler not found at {$script}");
        }

        return $script;
    }

    /**
     * The DSN of the database this dashboard is reading, so the spawned crawl
     * writes where the operator is looking.
     */
    private static function databaseUrl(): string
    {
        $connection = config('database.default');
        $c = config("database.connections.{$connection}");

        return sprintf(
            'postgresql://%s:%s@%s:%s/%s',
            rawurlencode((string) ($c['username'] ?? '')),
            rawurlencode((string) ($c['password'] ?? '')),
            $c['host'] ?? '127.0.0.1',
            $c['port'] ?? 5432,
            $c['database'] ?? ''
        );
    }
}
