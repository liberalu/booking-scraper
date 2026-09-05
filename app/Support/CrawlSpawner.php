<?php

declare(strict_types=1);

namespace App\Support;

use App\Contracts\RunLauncher;
use App\Runs\RunLaunchRequest;
use App\Runs\RunPhase;
use DateTimeImmutable;
use DateTimeZone;
use InvalidArgumentException;
use RuntimeException;

final class CrawlSpawner implements RunLauncher
{
    /** @return array{log: string, pid: int|null, cmd: list<string>} */
    public function spawn(
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

        return $this->spawnRequest(new RunLaunchRequest(
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
    public function spawnRequest(RunLaunchRequest $request): array
    {
        $binary = $this->phpBinary();
        if ($request->urls !== '') {
            $urls = CrawlerUrlPolicy::parse(
                $request->urls,
                Config::forShop($request->shop)->baseUrl(),
            );
            $request = new RunLaunchRequest(
                phase: $request->phase,
                shop: $request->shop,
                strategy: $request->strategy,
                mode: $request->mode,
                cronJobId: $request->cronJobId,
                role: $request->role,
                adoptRunId: $request->adoptRunId,
                urlsFile: $this->writeUrlManifest($urls),
            );
        }
        $cmd = self::buildCommand($request, $binary, base_path('bin'));

        $log = $this->logPath($request->role, $request->shop);
        $pid = $this->detach($cmd, $log, ['DATABASE_URL' => $this->databaseUrl()]);

        return ['log' => $log, 'pid' => $pid, 'cmd' => $cmd];
    }

    /** @return list<string> */
    public static function buildCommand(
        RunLaunchRequest $request,
        string $binary,
        string $binDirectory,
    ): array {
        $artisan = dirname(rtrim($binDirectory, '/')).'/artisan';
        if (! is_file($artisan)) {
            throw new RuntimeException("Run entry point not found at {$artisan}");
        }

        $command = match ($request->phase) {
            RunPhase::Scan, RunPhase::Discover => 'crawler:run',
            RunPhase::Match => 'books:match',
            RunPhase::Validate => 'books:validate',
        };
        $cmd = [$binary, $artisan, $command];
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
            } elseif ($request->urlsFile !== null) {
                $cmd[] = "--urls-file={$request->urlsFile}";
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

        return $cmd;
    }

    public static function logDir(): string
    {
        $dir = getenv('SPAWN_LOG_DIR');

        return is_string($dir) && $dir !== '' ? $dir : storage_path('logs/spawn');
    }

    private function logPath(string $role, string $shop): string
    {

        $stamp = (new DateTimeImmutable('now', new DateTimeZone('UTC')))
            ->format('Ymd-Hisu');

        return sprintf(
            '%s/spawn-%s-%s-%s.log',
            rtrim(self::logDir(), '/'),
            $stamp,
            $this->slug($role),
            $this->slug($shop)
        );
    }

    private function slug(string $value): string
    {
        $slug = preg_replace('/[^A-Za-z0-9._-]+/', '-', $value) ?? $value;

        $trimmed = trim($slug, '-');

        return $trimmed !== '' ? $trimmed : 'unknown';
    }

    /**
     * @param  list<string>  $cmd
     * @param  array<string, string>  $environment
     */
    private function detach(array $cmd, string $log, array $environment = []): ?int
    {
        $quoted = implode(' ', array_map(
            escapeshellarg(...),
            $cmd,
        ));
        $script = sprintf(
            'mkdir -p %s && nohup %s >> %s 2>&1 & echo $!',
            escapeshellarg(dirname($log)),
            $quoted,
            escapeshellarg($log)
        );

        $descriptors = [1 => ['pipe', 'w'], 2 => ['pipe', 'w']];
        $inherited = getenv();
        $process = @proc_open(
            ['/bin/sh', '-c', $script],
            $descriptors,
            $pipes,
            null,
            [...$inherited, ...$environment],
        );
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

    private function phpBinary(): string
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

    /** @param list<string> $urls */
    private function writeUrlManifest(array $urls): string
    {
        $directory = storage_path('app/crawl-input');
        if (! is_dir($directory) && ! mkdir($directory, 0700, true) && ! is_dir($directory)) {
            throw new RuntimeException("Could not create crawl input directory at {$directory}");
        }

        $path = tempnam($directory, 'urls-');
        if ($path === false || file_put_contents($path, implode("\n", $urls)."\n", LOCK_EX) === false) {
            throw new RuntimeException('Could not write crawl URL manifest');
        }
        chmod($path, 0600);

        return $path;
    }

    private function databaseUrl(): string
    {
        $connection = config('database.default');
        if (! is_string($connection) || $connection === '') {
            throw new RuntimeException('The default database connection is not configured.');
        }
        $configuration = config("database.connections.{$connection}");
        if (! is_array($configuration)) {
            throw new RuntimeException("Database connection '{$connection}' is not configured.");
        }

        $username = $this->configurationString($configuration['username'] ?? null, '');
        $password = $this->configurationString($configuration['password'] ?? null, '');
        $host = $this->configurationString($configuration['host'] ?? null, '127.0.0.1');
        $database = $this->configurationString($configuration['database'] ?? null, '');
        $port = $this->configurationPort($configuration['port'] ?? null);

        return sprintf(
            'postgresql://%s:%s@%s:%s/%s',
            rawurlencode($username),
            rawurlencode($password),
            $host,
            $port,
            $database,
        );
    }

    private function configurationString(mixed $value, string $default): string
    {
        return is_string($value) ? $value : $default;
    }

    private function configurationPort(mixed $value): int
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
