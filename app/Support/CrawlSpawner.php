<?php

declare(strict_types=1);

namespace App\Support;

use App\Runs\RunLaunchRequest;
use App\Runs\RunPhase;
use InvalidArgumentException;
use RuntimeException;

final class CrawlSpawner
{
    /** @return array{log: string, pid: int|null, cmd: list<string>} */
    public static function spawn(
        string $phase,
        string $shop,
        string $strategy = '',
        string $mode = 'delta',
        string $urls = '',
        ?int $cronJobId = null,
        string $role = 'operator',
        ?int $adoptRunId = null,
    ): array {
        $runPhase = RunPhase::tryFrom($phase);
        if ($runPhase === null) {
            throw new InvalidArgumentException("Unknown run phase: {$phase}");
        }

        return self::spawnRequest(new RunLaunchRequest(
            phase: $runPhase,
            shop: $shop,
            strategy: $strategy,
            mode: $mode,
            urls: $urls,
            cronJobId: $cronJobId,
            role: $role,
            adoptRunId: $adoptRunId,
        ));
    }

    /** @return array{log: string, pid: int|null, cmd: list<string>} */
    public static function spawnRequest(RunLaunchRequest $request): array
    {
        $binary = self::phpBinary();
        $cmd = self::buildCommand($request, $binary, base_path('bin'), self::databaseUrl());

        $log = self::logPath($request->role, $request->shop);
        $pid = self::detach($cmd, $log);

        return ['log' => $log, 'pid' => $pid, 'cmd' => $cmd];
    }

    /** @return list<string> */
    public static function buildCommand(
        RunLaunchRequest $request,
        string $binary,
        string $binDirectory,
        string $databaseUrl,
    ): array {
        $script = rtrim($binDirectory, '/').'/'.$request->phase->script();
        $artisan = dirname(rtrim($binDirectory, '/')).'/artisan';
        $usesCrawler = in_array($request->phase, [RunPhase::Scan, RunPhase::Discover], true);
        $target = $usesCrawler ? $artisan : $script;
        if (! is_file($target)) {
            throw new RuntimeException("Run entry point not found at {$target}");
        }

        $cmd = $usesCrawler
            ? [$binary, $artisan, 'crawler:run']
            : [$binary, $script];
        if (in_array($request->phase, [RunPhase::Scan, RunPhase::Discover], true)) {
            $cmd[] = $request->phase->value;
        }
        $cmd[] = "--shop={$request->shop}";

        if ($request->phase === RunPhase::Discover && $request->strategy !== '') {
            $cmd[] = "--strategy={$request->strategy}";
        }
        if ($request->phase === RunPhase::Scan) {
            if ($request->adoptRunId !== null) {
                $cmd[] = "--adopt-run-id={$request->adoptRunId}";
            } elseif ($request->urls !== '') {
                $cmd[] = "--urls={$request->urls}";
            } elseif ($request->mode === 'full') {
                $cmd[] = '--mode=full';
                $cmd[] = '--max-urls=0';
            } elseif ($request->mode === 'sample') {
                $cmd[] = '--max-urls=10';
            } else {
                $cmd[] = '--max-urls=0';
            }
        }
        if ($request->cronJobId !== null
            && in_array($request->phase, [RunPhase::Scan, RunPhase::Discover], true)) {
            $cmd[] = "--cron-job-id={$request->cronJobId}";
        }
        $cmd[] = "--database={$databaseUrl}";

        return $cmd;
    }

    public static function logDir(): string
    {
        $dir = getenv('SPAWN_LOG_DIR');

        return is_string($dir) && $dir !== '' ? $dir : storage_path('logs/spawn');
    }

    private static function logPath(string $role, string $shop): string
    {

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

        $trimmed = trim($slug, '-');

        return $trimmed !== '' ? $trimmed : 'unknown';
    }

    /** @param list<string> $cmd */
    private static function detach(array $cmd, string $log): ?int
    {
        $quoted = implode(' ', array_map(
            static fn (string $argument): string => escapeshellarg($argument),
            $cmd,
        ));
        $script = sprintf(
            'mkdir -p %s && nohup %s >> %s 2>&1 & echo $!',
            escapeshellarg(dirname($log)),
            $quoted,
            escapeshellarg($log)
        );

        $descriptors = [1 => ['pipe', 'w'], 2 => ['pipe', 'w']];
        $process = @proc_open(['/bin/sh', '-c', $script], $descriptors, $pipes);
        if (! is_resource($process)) {
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
                'Crawl spawn failed'.($err !== '' ? ": {$err}" : '')
            );
        }

        return ctype_digit($out) ? (int) $out : null;
    }

    private static function phpBinary(): string
    {
        $configured = getenv('CRAWLER_PHP_BINARY');
        if (is_string($configured) && $configured !== '' && is_executable($configured)) {
            return $configured;
        }
        foreach (['/opt/homebrew/opt/php@8.4/bin/php', PHP_BINARY] as $candidate) {
            if (is_executable($candidate)) {
                return $candidate;
            }
        }

        throw new RuntimeException('No PHP binary available to spawn the crawler');
    }

    private static function databaseUrl(): string
    {
        $connection = config('database.default');
        if (! is_string($connection) || $connection === '') {
            throw new RuntimeException('The default database connection is not configured.');
        }
        $configuration = config("database.connections.{$connection}");
        if (! is_array($configuration)) {
            throw new RuntimeException("Database connection '{$connection}' is not configured.");
        }

        $username = self::configurationString($configuration['username'] ?? null, '');
        $password = self::configurationString($configuration['password'] ?? null, '');
        $host = self::configurationString($configuration['host'] ?? null, '127.0.0.1');
        $database = self::configurationString($configuration['database'] ?? null, '');
        $port = self::configurationPort($configuration['port'] ?? null);

        return sprintf(
            'postgresql://%s:%s@%s:%s/%s',
            rawurlencode($username),
            rawurlencode($password),
            $host,
            $port,
            $database,
        );
    }

    private static function configurationString(mixed $value, string $default): string
    {
        return is_string($value) ? $value : $default;
    }

    private static function configurationPort(mixed $value): int
    {
        if (is_int($value)) {
            return $value;
        }
        if (is_string($value) && ctype_digit($value)) {
            return (int) $value;
        }

        return 5432;
    }
}
