"""Unit tests for the shell-wrapper that captures spawned-scrapy output.

``_spawn_scrapy_in_container`` (api.py) wraps the scrapy argv in
``sh -c`` so stdout+stderr land in a per-spawn log file inside the
scraper container. Without that wrapper, ``docker exec --detach``
discards subprocess output and a crash before the first heartbeat
tick is invisible — exactly the silence that hid run #427's failure
(2026-05-12).

These tests pin the wrapper's behaviour without booting FastAPI or
docker — the helper is pure list-of-strings in, list-of-strings out.
"""

from __future__ import annotations

from pathlib import Path

from book_scraper.dashboard.routes.api import _wrap_cmd_for_logging


def test_wrap_cmd_redirects_stdout_and_stderr_to_log_file() -> None:
    cmd = ["/app/.venv/bin/scrapy", "crawl", "validate", "-a", "shop=vaga"]
    log = Path("/var/log/scrapy_runs/spawn-20260513-operator-vaga.log")

    wrapped = _wrap_cmd_for_logging(cmd, log)

    assert wrapped[:2] == ["sh", "-c"]
    script = wrapped[2]
    # Both streams must be merged into the log file. `>> … 2>&1` is the
    # standard idiom; the test pins it so an accidental rewrite to
    # `> log` (truncating between two execs of the same shop) or
    # `2>/dev/null` (losing stderr — the stream scrapy actually uses
    # for log output) fails loudly.
    assert f">> {log} 2>&1" in script
    # Directory must be created in the target container — the dashboard
    # process cannot create paths cross-container.
    assert f"mkdir -p {log.parent}" in script
    # `exec` is required so docker tracks the scrapy PID after the
    # shell exits, otherwise detach=True races with shell teardown.
    assert "exec /app/.venv/bin/scrapy crawl validate -a shop=vaga" in script


def test_wrap_cmd_quotes_arguments_with_shell_metacharacters() -> None:
    """URL args can carry ``&`` / ``;`` / spaces. Without shell quoting
    they would either be interpreted by ``sh -c`` (command injection
    inside the container) or split into separate tokens."""
    cmd = [
        "/app/.venv/bin/scrapy",
        "crawl",
        "scan",
        "-a",
        "shop=vaga",
        "-a",
        "urls=https://example.com/?a=1&b=2;rm -rf /",
    ]
    log = Path("/var/log/scrapy_runs/spawn.log")

    script = _wrap_cmd_for_logging(cmd, log)[2]

    # The dangerous payload must be inside a single-quoted shell token,
    # never interpolated raw. If quoting regresses, the substring below
    # would appear unquoted and the test fails.
    assert "rm -rf /" in script  # still present …
    # … but as a literal arg, not a chained command. shlex.quote wraps
    # the entire `-a urls=…` value in single quotes, so the `;` cannot
    # terminate the scrapy command.
    assert "'urls=https://example.com/?a=1&b=2;rm -rf /'" in script


def test_wrap_cmd_quotes_log_path_with_spaces() -> None:
    """Defensive: the log path is derived from controlled inputs today,
    but pin quoting so a future change (per-run subdirectories named
    after shop slugs, etc.) can't silently break the wrapper."""
    log = Path("/var/log/scrapy runs/spawn weird name.log")
    wrapped = _wrap_cmd_for_logging(["/app/.venv/bin/scrapy", "version"], log)
    script = wrapped[2]
    assert "'/var/log/scrapy runs/spawn weird name.log'" in script
    assert "'/var/log/scrapy runs'" in script
