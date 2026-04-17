from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_all_categories,
    get_all_formats,
    get_listing_changes,
    get_listings_page,
    get_price_history,
    get_shop_by_name,
)
from book_scraper.dashboard.routes.scrape import MAX_FILTERED_URLS
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
    active: str = "",
    has_isbn: bool = False,
    shop: str = "",
    sort: str = "",
    order: str = "desc",
    scrape_started: str = "",
    session: Session = Depends(get_db),
):
    shop_obj = get_shop_by_name(session, shop) if shop else None
    shop_id = shop_obj.id if shop_obj else None
    listings, total = get_listings_page(
        session,
        page=page,
        search=q,
        author=author,
        publisher=publisher,
        category=category,
        format_filter=format,
        missing_field=missing,
        shop_id=shop_id,
        active_filter=active,
        has_isbn=has_isbn,
        sort_by=sort,
        sort_order=order,
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
            "active_filter": active,
            "has_isbn": has_isbn,
            "shop_filter": shop,
            "sort": sort,
            "order": order,
            "categories": categories,
            "formats": formats,
            "max_filtered_urls": MAX_FILTERED_URLS,
            "scrape_started": scrape_started,
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
    changes = get_listing_changes(session, listing_id)
    return templates.TemplateResponse(
        request,
        "listing_detail.html",
        {
            "active_page": "listings",
            "listing": listing,
            "prices": prices,
            "changes": changes,
        },
    )
