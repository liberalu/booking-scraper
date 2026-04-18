"""POST /scrape/filtered — launch a scan on the currently filtered shop_books.

The Scrapy scan spider already supports a single-URL mode via the
`urls=` argument (comma-separated). We resolve the active filters to
a concrete set of (shop, [urls]) pairs on the FastAPI side and spawn
one subprocess per shop that invokes `scrapy crawl scan -a shop=... -a
urls=...`. The subprocess is fire-and-forget — status and progress are
visible on /runs like any other run because the spider creates its
own scrape_run row.

A safety cap prevents accidentally spawning a multi-thousand-URL scan
that would be better served by a full rescrape.
"""

from __future__ import annotations

import shlex
import subprocess
from collections import defaultdict
from collections.abc import Callable
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, RedirectResponse, Response

from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import get_shop_books_page, get_shop_by_name
from book_scraper.dashboard.shop_book_filters import (
    get_shop_book_field_filter_params,
    parse_shop_book_field_filters,
)

router = APIRouter()

# Cap so a "filtered" scrape can't accidentally turn into a full
# catalog pass (we have `scan` without filters for that). The number
# is the count of URLs a single POST will spawn across all matching
# shops combined — narrow the filter or drop to a shop-specific scan
# if you hit it.
MAX_FILTERED_URLS = 5000


def _default_runner(cmd: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# Override in tests so we don't actually fork a scrapy process.
_subprocess_runner: Callable[[list[str]], subprocess.Popen[bytes]] = _default_runner


def set_subprocess_runner(
    runner: Callable[[list[str]], subprocess.Popen[bytes]],
) -> None:
    """Swap the subprocess launcher (test hook)."""
    global _subprocess_runner
    _subprocess_runner = runner


def _collect_shop_books(
    session: Session,
    shop_id: int | None,
    **filter_kwargs: str | bool,
) -> list[tuple[str, str]]:
    """Return every (shop_name, url) pair matching the filters.

    Pages through get_shop_books_page's filter logic until MAX+1 so we
    can detect over-cap cases without loading everything.
    """
    pairs: list[tuple[str, str]] = []
    page = 1
    per_page = 200
    while len(pairs) <= MAX_FILTERED_URLS:
        shop_books, _total = get_shop_books_page(
            session,
            page=page,
            per_page=per_page,
            shop_id=shop_id,
            **filter_kwargs,  # type: ignore[arg-type]
        )
        if not shop_books:
            break
        pairs.extend((shop_book.shop.name, shop_book.url) for shop_book in shop_books)
        if len(shop_books) < per_page:
            break
        page += 1
    return pairs


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
    field_filters = parse_shop_book_field_filters(request.query_params)
    # Require at least one filter so this endpoint can't be abused for
    # a silent full rescrape.
    has_any_filter = any(
        [
            shop,
            q,
            author,
            publisher,
            category,
            format,
            missing,
            active,
            has_isbn,
            bool(field_filters),
        ]
    )
    if not has_any_filter:
        raise HTTPException(
            status_code=400,
            detail=(
                "At least one filter is required "
                "(shop/q/author/publisher/category/format/missing/active/"
                "has_isbn/field filters)"
            ),
        )

    shop_id: int | None = None
    if shop:
        shop_obj = get_shop_by_name(session, shop)
        if shop_obj is None:
            raise HTTPException(status_code=404, detail=f"Unknown shop: {shop}")
        shop_id = shop_obj.id

    pairs = _collect_shop_books(
        session,
        shop_id,
        search=q,
        author=author,
        publisher=publisher,
        category=category,
        format_filter=format,
        missing_field=missing,
        active_filter=active,
        has_isbn=has_isbn,
        field_filters=field_filters,
    )

    if not pairs:
        raise HTTPException(status_code=404, detail="No shop_books matched the filters")
    if len(pairs) > MAX_FILTERED_URLS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Filter matches {len(pairs)}+ shop_books — over the "
                f"{MAX_FILTERED_URLS} cap. Narrow the filter, pick a "
                f"shop, or run `scrapy crawl scan` for a full pass."
            ),
        )

    # Group URLs by shop — one subprocess per shop keeps each run
    # scoped to a single spider config.
    by_shop: dict[str, list[str]] = defaultdict(list)
    for shop_name, url in pairs:
        by_shop[shop_name].append(url)

    jobs = []
    for shop_name, urls in by_shop.items():
        cmd = [
            "uv",
            "run",
            "scrapy",
            "crawl",
            "scan",
            "-a",
            f"shop={shop_name}",
            "-a",
            f"urls={','.join(urls)}",
        ]
        process = _subprocess_runner(cmd)
        summary = (
            shlex.join(cmd[:6]) + f" -a shop={shop_name} -a urls=<{len(urls)} urls>"
        )
        jobs.append(
            {
                "shop": shop_name,
                "urls_count": len(urls),
                "pid": getattr(process, "pid", None),
                "command": summary,
            }
        )

    # Browsers submit this form and expect to navigate somewhere sane,
    # not stare at a JSON payload. Redirect back to /shop-books with the
    # same filters plus a flash-style query param the template renders
    # as a toast. Clients that want structured output can still pass
    # `?output=json` to get the original response (using a custom param
    # name to avoid colliding with the `format` shop_book filter).
    wants_json = request.query_params.get("output") == "json"
    if wants_json:
        return JSONResponse(
            {"status": "started", "urls_count": len(pairs), "jobs": jobs},
            status_code=202,
        )
    back_params = {
        k: v
        for k, v in {
            "shop": shop,
            "q": q,
            "author": author,
            "publisher": publisher,
            "category": category,
            "format": format,
            "missing": missing,
            "active": active,
            "has_isbn": "true" if has_isbn else "",
        }.items()
        if v
    }
    back_params.update(get_shop_book_field_filter_params(field_filters))
    back_params["scrape_started"] = str(len(pairs))
    return RedirectResponse(
        url=f"/shop-books?{urlencode(back_params)}",
        status_code=303,
    )


# Make the test hook importable even if the caller imports the router.
__all__ = ["router", "set_subprocess_runner", "MAX_FILTERED_URLS"]
