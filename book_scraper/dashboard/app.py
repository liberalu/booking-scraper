from pathlib import Path

import markdown as _markdown
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from markupsafe import Markup

from book_scraper.dashboard.deps import templates
from book_scraper.dashboard.routes import (
    listings,
    overview,
    prices,
    runs,
    scrape,
    shops,
    urls,
    validation,
)


def _render_markdown(text: str | None) -> Markup:
    """Render a Markdown string to safe HTML for Jinja.

    Returns an empty Markup for None / empty inputs so templates can
    apply the filter unconditionally. Uses CommonMark-ish features
    (fenced_code, tables, nl2br) because scraped descriptions rely on
    paragraphs and line breaks more than fancy formatting.
    """
    if not text:
        return Markup("")
    html = _markdown.markdown(text, extensions=["extra", "nl2br"])
    return Markup(html)


templates.env.filters["markdown"] = _render_markdown

app = FastAPI(title="Book Scraper Dashboard")

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(overview.router)
app.include_router(shops.router)
app.include_router(listings.router)
app.include_router(runs.router)
app.include_router(urls.router)
app.include_router(validation.router)
app.include_router(prices.router)
app.include_router(scrape.router)
