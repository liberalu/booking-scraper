from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_all_categories,
    get_all_formats,
    get_listings_page,
    get_price_history,
)
from book_scraper.db.models import Listing

router = APIRouter()


@router.get("/listings")
def listings_page(
    request: Request,
    page: int = 1,
    q: str = "",
    author: str = "",
    publisher: str = "",
    category: str = "",
    format: str = "",
    missing: str = "",
    session: Session = Depends(get_db),
):
    listings, total = get_listings_page(
        session,
        page=page,
        search=q,
        author=author,
        publisher=publisher,
        category=category,
        format_filter=format,
        missing_field=missing,
    )
    categories = get_all_categories(session)
    formats = get_all_formats(session)
    total_pages = (total + 49) // 50
    return templates.TemplateResponse(
        request,
        "listings.html",
        {
            "active_page": "listings",
            "listings": listings,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "query": q,
            "author_filter": author,
            "publisher_filter": publisher,
            "category": category,
            "format_filter": format,
            "missing": missing,
            "categories": categories,
            "formats": formats,
        },
    )


@router.get("/listings/{listing_id}")
def listing_detail(
    listing_id: int,
    request: Request,
    session: Session = Depends(get_db),
):
    listing = session.get(Listing, listing_id)
    if listing is None:
        return HTMLResponse("Listing not found", status_code=404)
    prices = get_price_history(session, listing_id)
    return templates.TemplateResponse(
        request,
        "listing_detail.html",
        {
            "active_page": "listings",
            "listing": listing,
            "prices": prices,
        },
    )
