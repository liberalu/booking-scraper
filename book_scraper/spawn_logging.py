"""Per-spawn log capture for detached scrapy subprocesses.

Three call sites spawn `scrapy crawl …` as detached subprocesses:

  * `StallDetector._spawn_resume_subprocess` — auto-resume after a stall.
  * `CronChainTrigger._spawn_chain_subprocess` — chain a follow-on phase.
  * `dashboard/routes/scrape._default_runner` — operator-triggered run.

All three previously redirected stdout/stderr to ``DEVNULL``. That made
silent failures genuinely silent: a spawned spider could die before
emitting a single fetch and the only diagnostic was the run row's
``close_reason`` (verified painfully on patogupirkti runs 363–366,
2026-05-08, where the subprocess never logged anything we could find).

`open_spawn_log` captures both streams to a file under
``/var/log/scrapy_runs/`` named with the spawn timestamp, role, and
shop. The directory is shared with the dashboard via the
``scraper_logs`` Docker volume (mounted read-only there), so the
operator can find logs without `docker exec`.

Naming: ``spawn-YYYYMMDD-HHMMSSffffff-<role>-<shop>.log``
  * Sortable by timestamp.
  * `<role>` distinguishes `stall-resume` / `cron-chain` / `operator`
    so a debugger looking at "why did this spawn happen" can grep.
  * `<shop>` makes the multi-shop case scannable.

The file is opened in line-buffered mode (`buffering=1`) and merges
stderr into stdout — scrapy's logging mostly hits stderr. The fd is
returned to the caller so it can be passed straight to
`subprocess.Popen(stdout=, stderr=subprocess.STDOUT)`. Caller is
responsible for closing the fd after Popen returns; the spawned
process inherits its own duped descriptor.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)

# Where spawned-subprocess logs land. Lives under the `scraper_logs`
# Docker volume so the dashboard (which mounts the same volume read-only
# at `/var/log`) can serve them without `docker exec`.
SPAWN_LOG_DIR = Path("/var/log/scrapy_runs")

# Conservative slug pattern — keeps filenames safe across the volume's
# filesystem and trivial to glob from a shell. Anything outside [a-z0-9-]
# (after lowercasing) becomes `_`.
_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slug(value: str) -> str:
    return _SLUG_RE.sub("_", value.lower()).strip("_") or "unknown"


def open_spawn_log(role: str, shop: str) -> tuple[IO[bytes], Path]:
    """Open a per-spawn log file and return ``(handle, path)``.

    The handle is a binary, line-buffered file — pass it to
    ``subprocess.Popen(stdout=handle, stderr=subprocess.STDOUT)``. The
    caller closes it after `Popen` returns; the spawned process keeps
    its own duped fd.

    On any I/O error (volume missing, permission, disk full) we log a
    warning and fall back to ``os.devnull`` so the spawn still happens.
    Diagnostics > silence; spawning > diagnostics. The caller can rely
    on `path` being the actual file used, including the devnull fallback
    case.
    """
    try:
        SPAWN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "spawn_logging: cannot create %s (%s); falling back to /dev/null",
            SPAWN_LOG_DIR,
            exc,
        )
        return _open_devnull()

    timestamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%d-%H%M%S%f")
    name = f"spawn-{timestamp}-{_slug(role)}-{_slug(shop)}.log"
    path = SPAWN_LOG_DIR / name
    try:
        handle: IO[bytes] = open(path, "wb", buffering=0)  # noqa: SIM115
    except OSError as exc:
        logger.warning(
            "spawn_logging: cannot open %s (%s); falling back to /dev/null",
            path,
            exc,
        )
        return _open_devnull()
    return handle, path


def _open_devnull() -> tuple[IO[bytes], Path]:
    """Last-resort fallback so a spawn never fails because of logging."""
    devnull_path = Path(os.devnull)
    return open(devnull_path, "wb"), devnull_path  # noqa: SIM115
