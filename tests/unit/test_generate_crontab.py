"""Unit test for crontab line generation from cron_jobs rows."""

from types import SimpleNamespace


def test_build_crontab_lines_skips_disabled():
    from scripts.generate_crontab import build_crontab_lines

    jobs = [
        SimpleNamespace(
            id=1, shop=SimpleNamespace(name="vaga"),
            phase="discover", strategy="sitemap", args="",
            cron_expression="0 2 * * *", enabled=True,
        ),
        SimpleNamespace(
            id=2, shop=SimpleNamespace(name="vaga"),
            phase="scan", strategy=None, args="",
            cron_expression="0 3 * * *", enabled=False,
        ),
    ]
    lines = build_crontab_lines(jobs)
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
            id=1, shop=SimpleNamespace(name="vaga"),
            phase="scan", strategy=None, args="-a rescrape=true",
            cron_expression="0 4 * * *", enabled=True,
        ),
    ]
    lines = build_crontab_lines(jobs)
    assert len(lines) == 1
    line = lines[0]
    assert "scrapy crawl scan" in line
    assert "-a shop=vaga" in line
    assert "-a strategy" not in line  # no strategy for scan
    assert "-a rescrape=true" in line


def test_build_crontab_lines_empty_list_returns_no_lines():
    from scripts.generate_crontab import build_crontab_lines

    assert build_crontab_lines([]) == []
