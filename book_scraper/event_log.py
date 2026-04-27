"""JSONL per-response event log for postmortem and SSH tailing.

One line per response, written to ``logs/scrapy_events.log``. Designed
to be ``tail -f``-able and ``jq``-greppable. Live observability spec.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Anchor to the project root so the log is written to the same place
# regardless of the working directory at the time scrapy is invoked
# (cron job, docker exec, interactive shell, etc.).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_LOG_PATH = Path(
    os.environ.get(
        "SCRAPY_EVENTS_LOG",
        str(_PROJECT_ROOT / "logs" / "scrapy_events.log"),
    )
)
_log_path: Path | None = None


def _get_log_path() -> Path:
    global _log_path
    if _log_path is None:
        _log_path = _DEFAULT_LOG_PATH
        _log_path.parent.mkdir(parents=True, exist_ok=True)
    return _log_path


def log_response_event(
    *,
    run_id: int | None,
    url: str,
    status: int | None,
    duration_ms: int | None,
    request_delay_s: float | None,
    delay_source: str | None,
    retry_count: int,
    in_flight: int | None,
    bytes_: int | None,
    error_reason: str | None = None,
) -> None:
    """Append one JSON line per response to the events log.

    Failure here must never crash a scrape — a missing file or
    permission issue is logged and swallowed.
    """
    record: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "url": url,
        "status": status,
        "duration_ms": duration_ms,
        "request_delay_s": request_delay_s,
        "delay_source": delay_source,
        "retry_count": retry_count,
        "in_flight": in_flight,
        "bytes": bytes_,
    }
    if error_reason is not None:
        record["error_reason"] = error_reason
    try:
        path = _get_log_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("Failed to write event-log record")
