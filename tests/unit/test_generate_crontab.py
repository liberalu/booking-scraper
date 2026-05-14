"""Unit test for crontab line generation from cron_jobs rows."""

from types import SimpleNamespace


def _per_job_lines(lines: list[str]) -> list[str]:
    """Strip system-level entries (health-check, etc.) for per-job assertions.

    `build_crontab_lines` appends fixed system entries unconditionally —
    these tests assert behaviour over the dynamic per-job lines, so we
    filter the system ones out here. Their own coverage lives in
    `test_build_crontab_lines_appends_system_health_check`.
    """
    return [line for line in lines if "scripts/cron_health_check.py" not in line]


def test_build_crontab_lines_skips_disabled():
    from scripts.generate_crontab import build_crontab_lines

    jobs = [
        SimpleNamespace(
            id=1,
            shop=SimpleNamespace(name="vaga"),
            phase="discover",
            strategy="sitemap",
            args="",
            cron_expression="0 2 * * *",
            enabled=True,
        ),
        SimpleNamespace(
            id=2,
            shop=SimpleNamespace(name="vaga"),
            phase="scan",
            strategy=None,
            args="",
            cron_expression="0 3 * * *",
            enabled=False,
        ),
    ]
    lines = _per_job_lines(build_crontab_lines(jobs))
    assert len(lines) == 1
    assert "scrapy crawl discover" in lines[0]
    assert "-a shop=vaga" in lines[0]
    assert "-a strategy=sitemap" in lines[0]
    assert "0 2 * * *" in lines[0]
    assert ">> /var/log/scraper.log 2>&1" in lines[0]


def test_build_crontab_lines_scan_without_strategy():
    from scripts.generate_crontab import build_crontab_lines

    jobs = [
        SimpleNamespace(
            id=1,
            shop=SimpleNamespace(name="vaga"),
            phase="scan",
            strategy=None,
            args="-a rescrape=true",
            cron_expression="0 4 * * *",
            enabled=True,
        ),
    ]
    lines = _per_job_lines(build_crontab_lines(jobs))
    assert len(lines) == 1
    line = lines[0]
    assert "scrapy crawl scan" in line
    assert "-a shop=vaga" in line
    assert "-a strategy" not in line  # no strategy for scan
    assert "-a rescrape=true" in line


def test_build_crontab_lines_empty_list_returns_only_system_lines():
    """No per-job rows → system entries still ship.

    Empty cron_jobs table must not silently drop the health-check; the
    system entries are appended unconditionally so an operator can
    truncate the dynamic table without losing the heartbeat.
    """
    from scripts.generate_crontab import build_crontab_lines

    lines = build_crontab_lines([])
    assert _per_job_lines(lines) == []
    assert len(lines) >= 1
    assert any("cron_health_check.py" in line for line in lines)


def test_build_crontab_lines_includes_cron_job_id():
    from scripts.generate_crontab import build_crontab_lines

    jobs = [
        SimpleNamespace(
            id=42,
            shop=SimpleNamespace(name="vaga"),
            phase="discover",
            strategy="sitemap",
            args="",
            cron_expression="0 2 * * *",
            enabled=True,
        ),
    ]
    lines = _per_job_lines(build_crontab_lines(jobs))
    assert len(lines) == 1
    assert "-a cron_job_id=42" in lines[0]


def test_build_crontab_lines_appends_system_health_check():
    """Health-check line must be present on every regen, regardless of jobs."""
    from scripts.generate_crontab import build_crontab_lines

    jobs = [
        SimpleNamespace(
            id=1,
            shop=SimpleNamespace(name="vaga"),
            phase="discover",
            strategy="sitemap",
            args="",
            cron_expression="0 2 * * *",
            enabled=True,
        ),
    ]
    lines = build_crontab_lines(jobs)
    health_lines = [line for line in lines if "cron_health_check.py" in line]
    assert len(health_lines) == 1, "exactly one health-check entry expected"
    assert health_lines[0].startswith("0 3,9,15,21 * * *")
    assert ">> /var/log/scraper.log 2>&1" in health_lines[0]
