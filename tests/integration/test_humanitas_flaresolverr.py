"""End-to-end integration test for the FlareSolverr middleware path.

Hits a real FlareSolverr container at the configured endpoint and a
real humanitas.lt product URL — proves the bypass actually mints a
`cf_clearance` cookie, returns rendered HTML through our middleware,
and that the parser produces a parseable ProductPageResult.

Skipped by default to keep the unit suite hermetic. Opt in with:

    RUN_FLARESOLVERR_TESTS=1 FLARESOLVERR_ENDPOINT=http://localhost:8191/v1 \
        uv run pytest tests/integration/test_humanitas_flaresolverr.py -v
"""

from __future__ import annotations

import os

import httpx
import pytest

FS_ENDPOINT = os.environ.get("FLARESOLVERR_ENDPOINT", "http://localhost:8191/v1")
SAMPLE_PRODUCT_URL = (
    "https://www.humanitas.lt/produktas/visos-kategorijos/parasciu-vaikai/"
)


def _flaresolverr_reachable() -> bool:
    try:
        r = httpx.get(FS_ENDPOINT.rsplit("/", 1)[0] + "/", timeout=5)
        return r.status_code == 200 and "FlareSolverr" in r.text
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_FLARESOLVERR_TESTS") != "1",
        reason="set RUN_FLARESOLVERR_TESTS=1 to enable (needs FS sidecar reachable)",
    ),
    pytest.mark.skipif(
        not _flaresolverr_reachable(),
        reason=f"FlareSolverr not reachable at {FS_ENDPOINT}",
    ),
]


def _fs_post(body: dict) -> dict:
    """Plain POST to FS — mirrors what the middleware does, without Scrapy."""
    r = httpx.post(FS_ENDPOINT, json=body, timeout=120)
    r.raise_for_status()
    return r.json()


def test_flaresolverr_clears_cloudflare_challenge_for_humanitas() -> None:
    """Sanity check the bypass itself: real CF challenge → real product HTML."""
    data = _fs_post(
        {
            "cmd": "request.get",
            "url": SAMPLE_PRODUCT_URL,
            "maxTimeout": 90_000,
        }
    )
    assert data.get("status") == "ok", data.get("message")
    sol = data["solution"]
    assert sol["status"] == 200
    cookies = {c["name"]: c["value"] for c in sol.get("cookies", [])}
    assert "cf_clearance" in cookies, (
        "no cf_clearance cookie minted — challenge probably not solved; "
        f"got cookies: {list(cookies)}"
    )
    body = sol.get("response") or ""
    # Real product page sentinel: humanitas's product cart container.
    # If we hit the challenge page or the homepage fallback, this misses.
    assert (
        '<div class="book-info">' in body
        or 'data-product-id="' in body
    ), "FS returned a page that doesn't look like a humanitas product detail"


def test_humanitas_parser_handles_live_flaresolverr_response() -> None:
    """End-to-end: FS-rendered HTML → parser → fully populated ProductPageResult."""
    from book_scraper.spiders.humanitas.parsers import parse_product_page

    data = _fs_post(
        {
            "cmd": "request.get",
            "url": SAMPLE_PRODUCT_URL,
            "maxTimeout": 90_000,
        }
    )
    assert data.get("status") == "ok"
    html = data["solution"]["response"]
    parsed = parse_product_page(html)

    assert parsed["title"], "title missing — parser may need re-tuning"
    assert parsed["price"] is not None
    assert parsed["in_stock"] is True or parsed["in_stock"] is False
    assert parsed["sku"] is not None
    # parasciu-vaikai is a known-LT book with a Bookland ISBN.
    assert parsed["isbn"] == "9786094802966"
    assert parsed["author"] == "Loreta Tamulaitienė"
    assert parsed["year"] == 2022
    # Language gate accepts LT content.
    assert parsed["is_book_product"] is True
    props = parsed.get("properties")
    assert isinstance(props, dict)
    assert props.get("language") == "Lietuvių"
