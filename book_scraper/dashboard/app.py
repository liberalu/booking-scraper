from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from book_scraper.dashboard.routes import (
    inventory,
    logs,
    overview,
    prices,
    runs,
    validation,
)

app = FastAPI(title="Book Scraper Dashboard")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app.include_router(overview.router)
app.include_router(runs.router)
app.include_router(validation.router)
app.include_router(prices.router)
app.include_router(inventory.router)
app.include_router(logs.router)
