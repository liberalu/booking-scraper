# book_scraper/dashboard/routes/shops.py
from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from book_scraper.dashboard.deps import get_db
from book_scraper.dashboard.queries import get_shop_by_name
from book_scraper.db.models import ShopSettings

router = APIRouter()


def _upsert_setting(
    session: Session, shop_id: int, key: str, value: str, dtype: str
) -> None:
    existing = (
        session.query(ShopSettings)
        .filter(ShopSettings.shop_id == shop_id, ShopSettings.key == key)
        .first()
    )
    if existing:
        existing.value = value
        existing.type = dtype
    else:
        session.add(ShopSettings(shop_id=shop_id, key=key, value=value, type=dtype))


@router.post("/shops/{shop_name}/rate-settings")
def update_rate_settings(
    shop_name: str,
    download_delay: float = Form(...),
    concurrent_requests_per_domain: int = Form(...),
    session: Session = Depends(get_db),
) -> HTMLResponse:
    shop = get_shop_by_name(session, shop_name)
    if shop is None:
        return HTMLResponse('<p class="error">Shop not found</p>', status_code=404)
    if not (0.1 <= download_delay <= 60.0):
        return HTMLResponse(
            '<p class="error">download_delay must be 0.1–60 s</p>', status_code=400
        )
    if not (1 <= concurrent_requests_per_domain <= 16):
        return HTMLResponse(
            '<p class="error">concurrent_requests_per_domain must be 1–16</p>',
            status_code=400,
        )
    _upsert_setting(session, shop.id, "download_delay", str(download_delay), "float")
    _upsert_setting(
        session,
        shop.id,
        "concurrent_requests_per_domain",
        str(concurrent_requests_per_domain),
        "int",
    )
    session.commit()
    return HTMLResponse('<p class="success">Saved.</p>')
