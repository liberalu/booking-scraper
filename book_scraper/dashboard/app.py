from fastapi import FastAPI

from book_scraper.dashboard.routes import (
    inventory,
    logs,
    overview,
    prices,
    runs,
    validation,
)

app = FastAPI(title="Book Scraper Dashboard")

app.include_router(overview.router)
app.include_router(runs.router)
app.include_router(validation.router)
app.include_router(prices.router)
app.include_router(inventory.router)
app.include_router(logs.router)
