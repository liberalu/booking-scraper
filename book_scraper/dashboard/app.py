from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from book_scraper.dashboard.routes import (
    listings,
    overview,
    prices,
    runs,
    shops,
    urls,
    validation,
)

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
