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
# Pegasas's Magento occasionally 5xx's heavy pageSize=50 requests on
# cold cache; the spider subdivides the failed range into N smaller
# pageSize requests. Each subdivision lands on the Timeline so
# operators see when the backend got rough and the spider adapted —
# vs. the run going silent until the next stall.
SUBDIVIDED: Final = "subdivided"
# Single-row restart marker. Distinct from RESUMED_AFTER_FAILURE which
# was emitted on the *new* row when the chain-row model created one
# child row per process attempt. RESTARTED is emitted on the same
# logical-run row each time a process restart happens (stall, heartbeat
# timeout, boot reconcile). Operator-triggered restarts continue to use
# CONTINUED.
RESTARTED: Final = "restarted"
# Recorded on the parent run when a cron-chain fails to fire because the
# parent spider did not finish cleanly (stall, crash, operator stop, etc.).
# Makes chain gaps auditable without requiring operators to infer silence.
CHAIN_SKIPPED: Final = "chain_skipped"

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
        RESTARTED,
        COMPLETED,
        FAILED,
        SUBDIVIDED,
        CHAIN_SKIPPED,
    }
)

ACTOR_OPERATOR: Final = "operator"
ACTOR_SYSTEM: Final = "system"
