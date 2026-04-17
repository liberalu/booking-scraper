"""POST /scrape/filtered — launch a scan on the currently filtered listings.

The Scrapy scan spider already supports a single-URL mode via the
`urls=` argument (comma-separated). We resolve the active filters to
a concrete URL set on the FastAPI side and spawn a subprocess that
invokes `scrapy crawl scan -a shop=... -a urls=...`. The subprocess
is fire-and-forget — status and progress are visible on /runs like
any other run because the spider creates its own scrape_run row.

A safety cap prevents accidentally spawning a multi-thousand-URL
scan that would be better served by a full rescrape.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, Response

from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import get_listings_page, get_shop_by_name

router = APIRouter()

# Cap so a "filtered" scrape can't accidentally turn into a full
# catalog pass (we have `scan` without filters for that).
MAX_FILTERED_URLS = 1000


def _default_runner(cmd: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


# Override in tests so we don't actually fork a scrapy process.
_subprocess_runner: Callable[[list[str]], subprocess.Popen[bytes]] = _default_runner


def set_subprocess_runner(
    runner: Callable[[list[str]], subprocess.Popen[bytes]],
) -> None:
    """Swap the subprocess launcher (test hook)."""
    global _subprocess_runner
    _subprocess_runner = runner


def _collect_urls(
    session: Session, shop_id: int, **filter_kwargs: str | bool
) -> list[str]:
    """Return every listing URL matching the filters.

    Reuses get_listings_page's filter logic by paging through until we
    hit MAX_FILTERED_URLS + 1 so we can detect over-cap cases. The
    listings page default per_page is 50; we take a larger page here
    to keep the round-trip count small.
    """
    urls: list[str] = []
    page = 1
    per_page = 200
    while len(urls) <= MAX_FILTERED_URLS:
        listings, _total = get_listings_page(
            session,
            page=page,
            per_page=per_page,
            shop_id=shop_id,
            **filter_kwargs,  # type: ignore[arg-type]
        )
        if not listings:
            break
        urls.extend(listing.url for listing in listings)
        if len(listings) < per_page:
            break
        page += 1
    return urls


@router.post("/scrape/filtered")
def scrape_filtered(
    request: Request,
    shop: str = "",
    q: str = "",
    author: str = "",
    publisher: str = "",
    category: str = "",
    format: str = "",
    missing: str = "",
    active: str = "",
    has_isbn: bool = False,
    session: Session = Depends(get_db),
) -> Response:
    if not shop:
        raise HTTPException(
            status_code=400,
            detail=(
                "shop is required; full-catalog scrapes should use "
                "`scrapy crawl scan` directly"
            ),
        )
    shop_obj = get_shop_by_name(session, shop)
    if shop_obj is None:
        raise HTTPException(status_code=404, detail=f"Unknown shop: {shop}")

    # Require at least one filter so this endpoint can't be abused for
    # a silent full rescrape.
    has_any_filter = any(
        [q, author, publisher, category, format, missing, active, has_isbn]
    )
    if not has_any_filter:
        raise HTTPException(
            status_code=400,
            detail=(
                "At least one filter is required "
                "(q/author/publisher/category/format/missing/active/has_isbn)"
            ),
        )

    urls = _collect_urls(
        session,
        shop_obj.id,
        search=q,
        author=author,
        publisher=publisher,
        category=category,
        format_filter=format,
        missing_field=missing,
        active_filter=active,
        has_isbn=has_isbn,
    )

    if not urls:
        raise HTTPException(status_code=404, detail="No listings matched the filters")
    if len(urls) > MAX_FILTERED_URLS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Filter matches {len(urls)}+ listings — over the "
                f"{MAX_FILTERED_URLS} cap. Narrow the filter or run "
                f"`scrapy crawl scan -a shop={shop}` for a full pass."
            ),
        )

    cmd = [
        "uv",
        "run",
        "scrapy",
        "crawl",
        "scan",
        "-a",
        f"shop={shop}",
        "-a",
        f"urls={','.join(urls)}",
    ]
    process = _subprocess_runner(cmd)
    summary = (
        shlex.join(cmd[:6])
        + f" -a shop={shop} -a urls=<{len(urls)} urls>"
    )

    return JSONResponse(
        {
            "status": "started",
            "shop": shop,
            "urls_count": len(urls),
            "pid": getattr(process, "pid", None),
            "command": summary,
        },
        status_code=202,
    )


# Make the test hook importable even if the caller imports the router.
__all__ = ["router", "set_subprocess_runner", "MAX_FILTERED_URLS"]
