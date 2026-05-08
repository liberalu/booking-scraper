import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from book_scraper.dashboard.reaper import reaper_loop
from book_scraper.dashboard.routes import (
    api as api_routes,
)
from book_scraper.dashboard.routes import (
    scrape,
    shops,
)

_SPA_SCRIPT_RE = re.compile(
    r'<script type="text/babel" src="/static/hifi/(hf-[^"]+\.jsx)[^"]*"></script>'
)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(reaper_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Book Scraper Dashboard", lifespan=_lifespan)


@app.middleware("http")
async def _no_cache_jsx(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    if request.url.path.endswith(".jsx"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(api_routes.router, prefix="/api")


_SPA_INDEX_PATH = Path(__file__).parent / "static" / "hifi" / "index.html"
_SPA_HIFI_DIR = Path(__file__).parent / "static" / "hifi"


def _spa_html() -> HTMLResponse:
    """Serve the SPA with all JSX content inlined.

    Inlining bypasses every level of browser caching for the JSX modules
    — each request rebuilds the document from disk, so a dashboard
    rebuild reaches the browser on the next page load without manual
    hard-refresh.
    """
    html = _SPA_INDEX_PATH.read_text(encoding="utf-8")

    def _inline(match: "re.Match[str]") -> str:
        fname = match.group(1)
        content = (_SPA_HIFI_DIR / fname).read_text(encoding="utf-8")
        return f'<script type="text/babel" data-file="{fname}">\n{content}\n</script>'

    html = _SPA_SCRIPT_RE.sub(_inline, html)
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


# Every SPA page URL serves the same index.html — client-side routing
# in the SPA reads window.location.pathname to pick the page.
_SPA_FLAT_PATHS = [
    "/",
    "/runs",
    "/books",
    "/shop-books",
    "/urls",
    "/shops",
    "/cron",
    "/issues",
    "/prices",
    "/parser",
]
_SPA_DETAIL_PATHS = [
    "/runs/{rest:path}",
    "/books/{rest:path}",
    "/shop-books/{rest:path}",
    "/urls/{rest:path}",
    "/shops/{rest:path}",
    "/cron/{rest:path}",
    "/issues/{rest:path}",
]


async def _spa_index_flat() -> HTMLResponse:
    return _spa_html()


async def _spa_index_detail(rest: str = "") -> HTMLResponse:  # noqa: ARG001
    return _spa_html()


@app.get("/validation")
async def _redirect_validation(request: Request) -> RedirectResponse:
    qs = request.url.query
    target = "/issues" + (f"?{qs}" if qs else "")
    return RedirectResponse(url=target, status_code=301)


@app.get("/shops/{shop_name}/not-listed")
async def _redirect_not_listed(shop_name: str) -> RedirectResponse:
    return RedirectResponse(url=f"/shops/{shop_name}", status_code=301)


for _spa_path in _SPA_FLAT_PATHS:
    app.add_api_route(_spa_path, _spa_index_flat, methods=["GET"])
for _spa_path in _SPA_DETAIL_PATHS:
    app.add_api_route(_spa_path, _spa_index_detail, methods=["GET"])


app.include_router(shops.router)
app.include_router(scrape.router)
