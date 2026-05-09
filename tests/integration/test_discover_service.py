"""DiscoverService: prepare_discover seeds scrape_url_items per strategy."""

from types import SimpleNamespace

from book_scraper.db.models import ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import upsert_shop
from book_scraper.services.discover import DiscoverService


def _config(
    sitemap_url="https://vaga.lt/sitemap.xml",
    categories_url="https://vaga.lt/knygos?page={page}",
    full_crawl_start_url="https://vaga.lt/",
):
    return SimpleNamespace(
        discover=SimpleNamespace(
            sitemap=SimpleNamespace(url=sitemap_url),
            categories=SimpleNamespace(url=categories_url),
            full_crawl=SimpleNamespace(start_url=full_crawl_start_url),
        )
    )


def test_prepare_discover_sitemap_seeds_one_item(db_session):
    upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())

    items = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).all()
    assert len(items) == 1
    assert items[0].url == "https://vaga.lt/sitemap.xml"
    assert items[0].url_type == "sitemap"
    assert items[0].status == "pending"

    run = db_session.get(ScrapeRun, plan.run_id)
    assert run.phase == "discover_sitemap"
    assert run.status == "running"


def test_prepare_discover_categories_seeds_page_one(db_session):
    upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "categories", _config())

    items = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).all()
    assert len(items) == 1
    assert "page=1" in items[0].url
    assert items[0].url_type == "category_page"


def test_prepare_discover_full_crawl_seeds_start_url(db_session):
    upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "full_crawl", _config())

    items = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).all()
    assert len(items) == 1
    assert items[0].url == "https://vaga.lt/"
    assert items[0].url_type == "crawl"


def test_prepare_discover_resumes_running_run_with_pending_items(db_session):
    upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    first = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())

    second = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())
    assert second.run_id == first.run_id  # resumed, not new


def _lupasearch_config(
    endpoint="https://api.lupasearch.com/v1/query/abc",
    category_ids=("5107", "7352"),
    page_size=42,
):
    return SimpleNamespace(
        shop=SimpleNamespace(base_url="https://www.pegasas.lt"),
        discover=SimpleNamespace(
            lupasearch=SimpleNamespace(
                endpoint=endpoint,
                category_ids=list(category_ids),
                page_size=page_size,
                extra_filters=None,
            )
        ),
    )


def test_prepare_discover_lupasearch_seeds_synthetic_url(db_session):
    """The synthetic URL must carry offset/limit/category_ids so that
    the spider can rebuild the POST body during start() and after a
    resume — neither of which has access to anything beyond the URL."""
    upsert_shop(db_session, "pegasas", "https://www.pegasas.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover(
        "pegasas",
        "https://www.pegasas.lt",
        "lupasearch",
        _lupasearch_config(),
    )

    items = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).all()
    assert len(items) == 1
    seed = items[0]
    assert seed.url_type == "lupasearch_page"
    assert seed.status == "pending"
    assert seed.url.startswith("https://api.lupasearch.com/v1/query/abc?")
    assert "offset=0" in seed.url
    assert "limit=42" in seed.url
    assert "category_ids=5107%2C7352" in seed.url


def test_lupasearch_seed_round_trips_to_post_body(db_session):
    """Verify the URL stored in the queue rebuilds into the same POST
    body the spider would have sent for the original request — this is
    the contract the resume path depends on."""
    import json

    from book_scraper.spiders.lupasearch_urls import (
        build_lupasearch_post_request_kwargs,
    )

    upsert_shop(db_session, "pegasas", "https://www.pegasas.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover(
        "pegasas",
        "https://www.pegasas.lt",
        "lupasearch",
        _lupasearch_config(category_ids=("5107", "7352", "5125")),
    )

    seed = db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).one()
    kwargs = build_lupasearch_post_request_kwargs(seed.url)
    body = json.loads(kwargs["body"])
    assert kwargs["method"] == "POST"
    assert body["offset"] == 0
    assert body["limit"] == 42
    assert body["filters"]["category_ids"] == ["5107", "7352", "5125"]


def test_count_auto_resume_chain_depth(db_session):
    """Single-row restart model: depth = count of `restarted` events on
    the run. The StallDetector compares this against
    STALL_AUTO_RESUME_MAX before deciding whether to spawn another
    auto-resume.
    """
    from book_scraper.db import scrape_run_events as run_event_types
    from book_scraper.db.repo import (
        count_auto_resume_chain_depth,
        create_scrape_run,
        emit_scrape_run_event,
    )

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    run = create_scrape_run(db_session, shop.id, "discover_sitemap")
    db_session.commit()

    # Fresh run — no restart events.
    assert count_auto_resume_chain_depth(db_session, run.id) == 0

    for attempt in (1, 2, 3):
        emit_scrape_run_event(
            db_session,
            run.id,
            run_event_types.RESTARTED,
            payload={
                "attempt": attempt,
                "urls_processed_snapshot": 0,
                "previous_close_reason": "stall_timeout",
            },
            actor=run_event_types.ACTOR_SYSTEM,
        )
    db_session.commit()

    assert count_auto_resume_chain_depth(db_session, run.id) == 3


def test_count_consecutive_zero_progress_resumes(db_session):
    """Single-row restart model: streak counts `restarted` events whose
    `urls_processed_snapshot` matches the previous restart's snapshot
    (no progress between attempts). Threshold=2 makes the
    StallDetector circuit-break on structural bugs.
    """
    from book_scraper.db import scrape_run_events as run_event_types
    from book_scraper.db.repo import (
        count_consecutive_zero_progress_resumes,
        create_scrape_run,
        emit_scrape_run_event,
    )

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    run = create_scrape_run(db_session, shop.id, "scan")
    run.urls_processed = 0
    db_session.commit()

    # No restart events yet → streak 0.
    assert count_consecutive_zero_progress_resumes(db_session, run.id) == 0

    # Two restarts, both with zero-progress snapshot → streak >= 2.
    for snap in (0, 0):
        emit_scrape_run_event(
            db_session,
            run.id,
            run_event_types.RESTARTED,
            payload={
                "attempt": 1,
                "urls_processed_snapshot": snap,
                "previous_close_reason": "stall_timeout",
            },
            actor=run_event_types.ACTOR_SYSTEM,
        )
    db_session.commit()
    assert count_consecutive_zero_progress_resumes(db_session, run.id) >= 2

    # A subsequent restart that DID make progress (snapshot 5) breaks
    # the streak — newest pair (5,0) compares unequal.
    emit_scrape_run_event(
        db_session,
        run.id,
        run_event_types.RESTARTED,
        payload={
            "attempt": 3,
            "urls_processed_snapshot": 5,
            "previous_close_reason": "stall_timeout",
        },
        actor=run_event_types.ACTOR_SYSTEM,
    )
    db_session.commit()
    assert count_consecutive_zero_progress_resumes(db_session, run.id) == 0


def test_prepare_discover_reuses_failed_resumable_row(db_session):
    from datetime import UTC, datetime
    from book_scraper.db import scrape_run_events as run_event_types
    from book_scraper.db.models import ScrapeRun
    from book_scraper.db.repo import (
        create_scrape_run, insert_scrape_url_item, upsert_shop,
    )
    from book_scraper.services.discover import DiscoverService

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    failed = create_scrape_run(db_session, shop.id, "discover_sitemap")
    failed.status = "failed"
    failed.finished_at = datetime.now(UTC)
    failed.close_reason = "stall_timeout"
    failed.resumable_after_failure = True
    failed.urls_processed = 0
    insert_scrape_url_item(
        db_session, run_id=failed.id, shop_id=shop.id,
        discovered_url_id=None, url="https://vaga.lt/sitemap.xml",
        url_type="sitemap",
    )
    db_session.commit()
    failed_id = failed.id
    pre_count = db_session.query(ScrapeRun).count()

    plan = DiscoverService(db_session).prepare_discover(
        "vaga", "https://vaga.lt", "sitemap", _config()
    )
    db_session.commit()

    assert db_session.query(ScrapeRun).count() == pre_count
    assert plan.run_id == failed_id
    refreshed = db_session.get(ScrapeRun, failed_id)
    assert refreshed.status == "running"
    assert any(
        e.event_type == run_event_types.RESTARTED for e in refreshed.events
    )


def test_finish_discover_keeps_staging_rows(db_session):
    """scrape_url_items used to be deleted on discover finish; they're now
    kept as the source of truth for per-URL run history (see commit
    history: cleanup_scrape_url_items removed)."""
    upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.commit()

    service = DiscoverService(db_session)
    plan = service.prepare_discover("vaga", "https://vaga.lt", "sitemap", _config())
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 1

    service.finish_discover(plan.run_id, urls_processed=1, reason="finished")
    assert db_session.query(ScrapeUrlItem).filter_by(run_id=plan.run_id).count() == 1
