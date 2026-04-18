"""POST /scrape/filtered — verify it resolves filters to URLs and spawns
a subprocess with the right args."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from book_scraper.dashboard.app import app
from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.routes import scrape as scrape_route
from book_scraper.db.models import Shop, ShopBook


class _FakeProcess:
    def __init__(self, pid: int = 42):
        self.pid = pid


@pytest.fixture()
def captured_cmd() -> list[list[str]]:
    """Swap the subprocess runner for a capture-only stub."""
    captured: list[list[str]] = []

    def runner(cmd: list[str]) -> _FakeProcess:  # type: ignore[override]
        captured.append(cmd)
        return _FakeProcess()

    original = scrape_route._subprocess_runner
    scrape_route.set_subprocess_runner(runner)  # type: ignore[arg-type]
    try:
        yield captured
    finally:
        scrape_route.set_subprocess_runner(original)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _seed(db_session: Session) -> None:
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    db_session.add_all(
        [
            ShopBook(
                shop_id=shop.id,
                url=f"https://vaga.lt/a-{i}",
                title=f"Title {i}",
                author="Alice",
            )
            for i in range(3)
        ]
    )
    db_session.add_all(
        [
            ShopBook(
                shop_id=shop.id,
                url="https://vaga.lt/other",
                title="Other",
                author="Bob",
            ),
            ShopBook(
                shop_id=shop.id,
                url="https://vaga.lt/empty-author",
                title="Empty Author",
                author="",
            ),
            ShopBook(
                shop_id=shop.id,
                url="https://vaga.lt/null-author",
                title="Null Author",
                author=None,
            ),
        ]
    )
    db_session.flush()


def test_scrape_filtered_rejects_unfiltered_request(
    client: TestClient, captured_cmd: list[list[str]]
) -> None:
    resp = client.post("/scrape/filtered")
    assert resp.status_code == 400
    assert captured_cmd == []


def test_scrape_filtered_404_when_no_matches(
    client: TestClient, captured_cmd: list[list[str]]
) -> None:
    resp = client.post("/scrape/filtered?shop=vaga&author=DoesNotExist")
    assert resp.status_code == 404
    assert captured_cmd == []


def test_scrape_filtered_spawns_with_correct_urls(
    client: TestClient, captured_cmd: list[list[str]]
) -> None:
    """Default POST redirects back to shop_books with a flash flag."""
    resp = client.post("/scrape/filtered?shop=vaga&author=Alice")
    assert resp.status_code == 303
    assert "/shop-books?" in resp.headers["location"]
    assert "scrape_started=3" in resp.headers["location"]

    assert len(captured_cmd) == 1
    cmd = captured_cmd[0]
    assert "scrapy" in cmd
    assert "crawl" in cmd
    assert "scan" in cmd
    # The -a urls=... arg should contain only the 3 Alice URLs.
    urls_arg = next(a for a in cmd if a.startswith("urls="))
    urls = urls_arg.removeprefix("urls=").split(",")
    assert len(urls) == 3
    for url in urls:
        assert url.startswith("https://vaga.lt/a-")
    assert "https://vaga.lt/other" not in urls


def test_scrape_filtered_json_mode(
    client: TestClient, captured_cmd: list[list[str]]
) -> None:
    """?output=json preserves the structured response for API callers."""
    resp = client.post("/scrape/filtered?shop=vaga&author=Alice&output=json")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "started"
    assert body["urls_count"] == 3
    assert len(body["jobs"]) == 1


def test_scrape_filtered_without_shop_uses_filter_alone(
    client: TestClient, captured_cmd: list[list[str]]
) -> None:
    """Filter-only (no shop) should still work — endpoint groups URLs
    by shop and spawns a subprocess per shop."""
    resp = client.post("/scrape/filtered?author=Alice&output=json")
    assert resp.status_code == 202
    body = resp.json()
    assert body["urls_count"] == 3
    assert {job["shop"] for job in body["jobs"]} == {"vaga"}
    assert len(captured_cmd) == 1


def test_scrape_filtered_over_cap_returns_413(
    client: TestClient,
    captured_cmd: list[list[str]],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Lower the cap so we don't have to seed thousands of rows.
    monkeypatch.setattr(scrape_route, "MAX_FILTERED_URLS", 2)
    resp = client.post("/scrape/filtered?shop=vaga&author=Alice")
    assert resp.status_code == 413
    assert captured_cmd == []


def test_scrape_filtered_supports_shared_field_filters(
    client: TestClient, captured_cmd: list[list[str]]
) -> None:
    resp = client.post("/scrape/filtered?field_author_op=empty&output=json")
    assert resp.status_code == 202
    body = resp.json()
    assert body["urls_count"] == 2

    assert len(captured_cmd) == 1
    urls_arg = next(a for a in captured_cmd[0] if a.startswith("urls="))
    urls = urls_arg.removeprefix("urls=").split(",")
    assert set(urls) == {
        "https://vaga.lt/empty-author",
        "https://vaga.lt/null-author",
    }
