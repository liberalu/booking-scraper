from types import SimpleNamespace
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db, templates
from book_scraper.dashboard.queries import (
    get_all_categories,
    get_all_formats,
    get_all_types,
    get_attribute_keys,
    get_attribute_values,
    get_field_history,
    get_field_updates,
    get_price_history,
    get_shop_book_changes,
    get_shop_book_issues,
    get_shop_books_page,
    get_shop_by_name,
)
from book_scraper.dashboard.routes.scrape import MAX_FILTERED_URLS
from book_scraper.dashboard.shop_book_filters import (
    FIELD_SPEC_BY_NAME,
    GENERIC_FIELD_OPERATORS,
    describe_shop_book_field_filter,
    get_shop_book_field_filter_params,
    get_shop_book_field_options,
    parse_shop_book_field_filters,
)
from book_scraper.db.models import ShopBook
from book_scraper.spiders.vaga.parsers import classify_book_product

router = APIRouter()


def _build_shop_books_url(params: dict[str, str]) -> str:
    query = urlencode(params)
    return f"/shop-books?{query}" if query else "/shop-books"


def _get_type_score(shop_book: ShopBook) -> dict[str, object] | None:
    if shop_book.shop.name != "vaga":
        return None

    attributes = {
        attr.key: attr.value
        for attr in shop_book.attributes
        if attr.value not in (None, "")
    }
    author = shop_book.author
    if not author and shop_book.authors:
        author = ", ".join(a.name for a in shop_book.authors if a.name)

    classification = classify_book_product(
        {
            "title": shop_book.title,
            "author": author,
            "isbn": shop_book.isbn,
            "categories": shop_book.categories or [],
            "year": shop_book.year,
            "format": shop_book.format,
            "pages": attributes.get("pages"),
            "cover_type": attributes.get("cover_type"),
            "translator": attributes.get("translator"),
            "narrator": attributes.get("narrator"),
            "duration": attributes.get("duration"),
            "schema_types": [],
        }
    )
    return {
        "score": classification["score"],
        "reasons": classification["reasons"],
        "type": shop_book.type,
    }


@router.get("/shop-books")
def shop_books_page(
    request: Request,
    page: int = 1,
    q: str = "",
    author: str = "",
    publisher: str = "",
    category: str = "",
    type: str = "",
    format: str = "",
    missing: str = "",
    active: str = "true",
    has_isbn: bool = False,
    shop: str = "",
    sort: str = "",
    order: str = "desc",
    scrape_started: str = "",
    attr_key: str = "",
    attr_value: str = "",
    session: Session = Depends(get_db),
):
    field_filters = parse_shop_book_field_filters(request.query_params)
    field_filter_params = get_shop_book_field_filter_params(field_filters)
    builder_field_name = request.query_params.get("field_name", "")
    builder_spec = FIELD_SPEC_BY_NAME.get(builder_field_name)
    builder_operator = request.query_params.get("field_op", "any")
    builder_value = request.query_params.get("field_value", "")
    active_field_filters = [
        {
            "name": field_name,
            "operator": field_filter["operator"],
            "value": field_filter.get("value", ""),
        }
        for field_name, field_filter in field_filters.items()
    ]
    shop_obj = get_shop_by_name(session, shop) if shop else None
    shop_id = shop_obj.id if shop_obj else None
    shop_books, total = get_shop_books_page(
        session,
        page=page,
        search=q,
        author=author,
        publisher=publisher,
        category=category,
        type_filter=type,
        format_filter=format,
        missing_field=missing,
        shop_id=shop_id,
        active_filter=active,
        has_isbn=has_isbn,
        sort_by=sort,
        sort_order=order,
        field_filters=field_filters,
        attr_key=attr_key,
        attr_value=attr_value,
    )
    categories = get_all_categories(session)
    types = get_all_types(session)
    formats = get_all_formats(session)
    attribute_keys = get_attribute_keys(session, shop_id=shop_id)
    attribute_values = (
        get_attribute_values(session, attr_key, shop_id=shop_id) if attr_key else []
    )
    total_pages = (total + 49) // 50

    filter_params: dict[str, str] = {
        k: v
        for k, v in {
            "q": q,
            "author": author,
            "publisher": publisher,
            "category": category,
            "type": type,
            "format": format,
            "missing": missing,
            "active": active,
            "shop": shop,
            "has_isbn": "true" if has_isbn else "",
            "attr_key": attr_key,
            "attr_value": attr_value,
        }.items()
        if v
    }
    filter_params.update(field_filter_params)
    has_visible_filters = any(
        [
            q,
            author,
            publisher,
            category,
            type,
            format,
            missing,
            shop,
            has_isbn,
            active != "true",
            bool(field_filters),
            attr_key,
        ]
    )

    filter_params_string = urlencode(filter_params)
    filter_and_sort_params = dict(filter_params)
    if sort:
        filter_and_sort_params["sort"] = sort
        filter_and_sort_params["order"] = order
    filter_and_sort_params_string = urlencode(filter_and_sort_params)
    reset_params = {"sort": sort, "order": order} if sort else {}

    filter_badges: list[dict[str, str]] = []
    badge_specs = [
        ("q", f'Search: "{q}"'),
        ("author", f'Author: "{author}"'),
        ("publisher", f'Publisher: "{publisher}"'),
        ("category", f"Category: {category}"),
        ("type", f"Type: {type}"),
        ("format", f"Format: {format}"),
        ("missing", f"Missing: {missing}"),
        ("shop", f"Shop: {shop}"),
    ]
    for key, label in badge_specs:
        value = filter_params.get(key)
        if not value:
            continue
        params = dict(filter_and_sort_params)
        params.pop(key, None)
        filter_badges.append(
            {"label": label, "remove_url": _build_shop_books_url(params)}
        )

    if has_isbn:
        params = dict(filter_and_sort_params)
        params.pop("has_isbn", None)
        filter_badges.append(
            {"label": "Has ISBN", "remove_url": _build_shop_books_url(params)}
        )

    if active == "false":
        params = dict(filter_and_sort_params)
        params["active"] = "true"
        filter_badges.append(
            {"label": "Inactive", "remove_url": _build_shop_books_url(params)}
        )
    elif active == "all":
        params = dict(filter_and_sort_params)
        params["active"] = "true"
        filter_badges.append(
            {"label": "All statuses", "remove_url": _build_shop_books_url(params)}
        )

    for field_name, field_filter in field_filters.items():
        params = dict(filter_and_sort_params)
        params.pop(f"field_{field_name}_op", None)
        params.pop(f"field_{field_name}_value", None)
        filter_badges.append(
            {
                "label": describe_shop_book_field_filter(field_name, field_filter),
                "remove_url": _build_shop_books_url(params),
            }
        )

    if attr_key:
        attr_label = f"Attr: {attr_key}" + (
            f"={attr_value}" if attr_value else " (any)"
        )
        params = dict(filter_and_sort_params)
        params.pop("attr_key", None)
        params.pop("attr_value", None)
        filter_badges.append(
            {"label": attr_label, "remove_url": _build_shop_books_url(params)}
        )

    return templates.TemplateResponse(
        request,
        "shop_books.html",
        {
            "active_page": "shop_books",
            "shop_books": shop_books,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "query": q,
            "author_filter": author,
            "publisher_filter": publisher,
            "category": category,
            "type_filter": type,
            "format_filter": format,
            "missing": missing,
            "active_filter": active,
            "has_isbn": has_isbn,
            "shop_filter": shop,
            "sort": sort,
            "order": order,
            "categories": categories,
            "types": types,
            "formats": formats,
            "attr_key": attr_key,
            "attr_value": attr_value,
            "attribute_keys": attribute_keys,
            "attribute_values": attribute_values,
            "max_filtered_urls": MAX_FILTERED_URLS,
            "scrape_started": scrape_started,
            "secondary_filters_active": bool(
                author or publisher or category or type or format or missing or attr_key
            ),
            "field_filters_active": bool(field_filters),
            "field_filter_options": get_shop_book_field_options(),
            "field_filter_operator_options": [
                {"value": value, "label": label}
                for value, label in GENERIC_FIELD_OPERATORS
            ],
            "builder_field_name": builder_field_name,
            "builder_operator": builder_operator,
            "builder_value": builder_value,
            "builder_placeholder": builder_spec.placeholder if builder_spec else "",
            "active_field_filters": active_field_filters,
            "filter_params": filter_params_string,
            "filter_and_sort_params": filter_and_sort_params_string,
            "filter_badges": filter_badges,
            "has_active_filters": bool(filter_params),
            "has_visible_filters": has_visible_filters,
            "reset_url": _build_shop_books_url(reset_params),
        },
    )


@router.get("/shop-books/{shop_book_id}")
def shop_book_detail(
    shop_book_id: int,
    request: Request,
    session: Session = Depends(get_db),
):
    shop_book = session.get(ShopBook, shop_book_id)
    if shop_book is None:
        return HTMLResponse("Shop book not found", status_code=404)
    prices = get_price_history(session, shop_book_id)
    changes = get_shop_book_changes(session, shop_book_id)
    field_updates = get_field_updates(session, shop_book_id)
    field_history = get_field_history(session, shop_book_id)
    issues = get_shop_book_issues(session, shop_book_id)
    type_score = _get_type_score(shop_book)

    # Build unified change history: field changes plus price/stock changes
    # derived from the prices table.
    all_changes: list = list(changes)
    for i in range(1, len(prices)):
        prev, cur = prices[i - 1], prices[i]
        if cur.price != prev.price:
            all_changes.append(
                SimpleNamespace(
                    changed_at=cur.scraped_at,
                    field="price",
                    old_value=str(prev.price),
                    new_value=str(cur.price),
                    scrape_run_id=cur.scrape_run_id,
                )
            )
        if cur.in_stock != prev.in_stock:
            all_changes.append(
                SimpleNamespace(
                    changed_at=cur.scraped_at,
                    field="in_stock",
                    old_value="In stock" if prev.in_stock else "Out of stock",
                    new_value="In stock" if cur.in_stock else "Out of stock",
                    scrape_run_id=cur.scrape_run_id,
                )
            )
    all_changes.sort(key=lambda c: c.changed_at, reverse=True)

    return templates.TemplateResponse(
        request,
        "shop_book_detail.html",
        {
            "active_page": "shop_books",
            "shop_book": shop_book,
            "prices": prices,
            "changes": all_changes,
            "field_updates": field_updates,
            "field_history": field_history,
            "issues": issues,
            "type_score": type_score,
        },
    )
