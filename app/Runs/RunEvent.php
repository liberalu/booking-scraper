<?php

declare(strict_types=1);

namespace App\Runs;

final class RunEvent
{
    public const string STARTED = 'started';

    public const string PAUSED = 'paused';

    public const string RESUMED = 'resumed';

    public const string STOP_REQUESTED = 'stop_requested';

    public const string RETRY_FAILURES = 'retry_failures';

    public const string REQUEST_RETRIED = 'request_retried';

    public const string RERUN = 'rerun';

    public const string CONTINUED = 'continued';

    public const string RESUMED_AFTER_FAILURE = 'resumed_after_failure';

    public const string COMPLETED = 'completed';

    public const string FAILED = 'failed';

    public const string SUBDIVIDED = 'subdivided';

    public const string RESTARTED = 'restarted';

    public const string CHAIN_SKIPPED = 'chain_skipped';

    public const string ACTOR_OPERATOR = 'operator';

    public const string ACTOR_SYSTEM = 'system';

    public const array ALL = [
        self::STARTED, self::PAUSED, self::RESUMED, self::STOP_REQUESTED,
        self::RETRY_FAILURES, self::REQUEST_RETRIED, self::RERUN, self::CONTINUED,
        self::RESUMED_AFTER_FAILURE, self::RESTARTED, self::COMPLETED,
        self::FAILED, self::SUBDIVIDED, self::CHAIN_SKIPPED,
    ];
}
