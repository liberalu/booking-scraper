"""Constants for scrape_run_events lifecycle log."""

from typing import Final

STARTED: Final = "started"
PAUSED: Final = "paused"
RESUMED: Final = "resumed"
STOP_REQUESTED: Final = "stop_requested"
RETRY_FAILURES: Final = "retry_failures"
RERUN: Final = "rerun"
CONTINUED: Final = "continued"
RESUMED_AFTER_FAILURE: Final = "resumed_after_failure"
COMPLETED: Final = "completed"
FAILED: Final = "failed"

EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        STARTED,
        PAUSED,
        RESUMED,
        STOP_REQUESTED,
        RETRY_FAILURES,
        RERUN,
        CONTINUED,
        RESUMED_AFTER_FAILURE,
        COMPLETED,
        FAILED,
    }
)

ACTOR_OPERATOR: Final = "operator"
ACTOR_SYSTEM: Final = "system"
