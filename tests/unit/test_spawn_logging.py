"""Unit tests for the per-spawn log capture helper."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from book_scraper import spawn_logging


def test_slug_normalises_to_filesystem_safe_chars() -> None:
    assert spawn_logging._slug("patogupirkti") == "patogupirkti"
    assert spawn_logging._slug("Stall Resume") == "stall_resume"
    assert spawn_logging._slug("ÅÆ_./?") == "unknown"
    # Hyphens are preserved (they're safe and we want them in role names).
    assert spawn_logging._slug("cron-chain") == "cron-chain"
    # Empty / pathological inputs fall back to "unknown" so paths never
    # collapse to leading dashes.
    assert spawn_logging._slug("") == "unknown"
    assert spawn_logging._slug("___") == "unknown"


def test_open_spawn_log_writes_to_file_with_descriptive_name(
    tmp_path: Path,
) -> None:
    """The handle must be writable and the path must include role + shop
    so a debugger looking at the log directory can grep for the spawn
    they care about."""
    with patch.object(spawn_logging, "SPAWN_LOG_DIR", tmp_path / "scrapy_runs"):
        handle, path = spawn_logging.open_spawn_log("stall-resume", "patogupirkti")

    try:
        # File path conventions: starts with "spawn-", ends with ".log",
        # contains the role and the shop so `ls /var/log/scrapy_runs |
        # grep patogupirkti` works.
        assert path.name.startswith("spawn-")
        assert path.name.endswith(".log")
        assert "stall-resume" in path.name
        assert "patogupirkti" in path.name
        # The directory was auto-created by the helper (the parent of
        # tmp_path/scrapy_runs didn't exist when we patched).
        assert path.parent.exists()
        # Handle is binary and writable — exactly what subprocess.Popen
        # expects for stdout=.
        handle.write(b"hello world\n")
    finally:
        handle.close()

    # Subprocess output round-trips through the file (we just wrote one
    # line; the file should now contain it).
    assert path.read_bytes() == b"hello world\n"


def test_open_spawn_log_falls_back_to_devnull_on_io_error(tmp_path: Path) -> None:
    """If the log directory can't be created (volume missing, permission,
    disk full), the helper logs a warning and returns ``/dev/null`` so
    the spawn still happens. A subprocess that loses logs is bad; a
    subprocess that doesn't run at all is worse."""
    # Point at a path under a nonexistent device-like prefix so mkdir
    # really fails (writing to /dev/null itself works, and PermissionError
    # is hard to reliably provoke in CI). Mock mkdir to raise OSError
    # directly — that's what every real failure mode boils down to.
    with patch.object(spawn_logging.Path, "mkdir", side_effect=OSError("disk full")):
        handle, path = spawn_logging.open_spawn_log("operator", "vaga")
    try:
        assert path == Path(os.devnull)
        # Devnull is writable even when mkdir would have failed.
        handle.write(b"discarded\n")
    finally:
        handle.close()


def test_open_spawn_log_uses_microsecond_timestamp_for_uniqueness(
    tmp_path: Path,
) -> None:
    """Two back-to-back spawns must not race on the same filename. The
    timestamp portion includes microseconds — tight loops produce
    distinct paths even within the same second."""
    with patch.object(spawn_logging, "SPAWN_LOG_DIR", tmp_path):
        h1, p1 = spawn_logging.open_spawn_log("operator", "vaga")
        h2, p2 = spawn_logging.open_spawn_log("operator", "vaga")
    try:
        assert p1 != p2
    finally:
        h1.close()
        h2.close()


def test_compute_spawn_log_path_is_pure_and_matches_open_naming(
    tmp_path: Path,
) -> None:
    """``compute_spawn_log_path`` returns a path without touching the
    filesystem — the dashboard uses it to predict the log path inside
    the scraper container before issuing ``docker exec``."""
    with patch.object(spawn_logging, "SPAWN_LOG_DIR", tmp_path / "missing"):
        path = spawn_logging.compute_spawn_log_path("operator", "vaga")
    # Same convention as open_spawn_log so logs from both paths sort
    # together in `ls`.
    assert path.name.startswith("spawn-")
    assert path.name.endswith(".log")
    assert "operator" in path.name
    assert "vaga" in path.name
    # Pure function: no directory was created even though we pointed at
    # a non-existent parent.
    assert not path.parent.exists()
