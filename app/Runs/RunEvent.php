<?php

declare(strict_types=1);

namespace App\Runs;

final class RunEvent
{
    public const STARTED = 'started';

    public const PAUSED = 'paused';

    public const RESUMED = 'resumed';

    public const STOP_REQUESTED = 'stop_requested';

    public const RETRY_FAILURES = 'retry_failures';

    public const REQUEST_RETRIED = 'request_retried';

    public const RERUN = 'rerun';

    public const CONTINUED = 'continued';

    public const RESUMED_AFTER_FAILURE = 'resumed_after_failure';

    public const COMPLETED = 'completed';

    public const FAILED = 'failed';

    public const SUBDIVIDED = 'subdivided';

    public const RESTARTED = 'restarted';

    public const CHAIN_SKIPPED = 'chain_skipped';

    public const ACTOR_OPERATOR = 'operator';

    public const ACTOR_SYSTEM = 'system';

    public const ALL = [
        self::STARTED, self::PAUSED, self::RESUMED, self::STOP_REQUESTED,
        self::RETRY_FAILURES, self::REQUEST_RETRIED, self::RERUN, self::CONTINUED,
        self::RESUMED_AFTER_FAILURE, self::RESTARTED, self::COMPLETED,
        self::FAILED, self::SUBDIVIDED, self::CHAIN_SKIPPED,
    ];
}
