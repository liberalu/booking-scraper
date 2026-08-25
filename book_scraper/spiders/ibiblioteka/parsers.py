"""Parsers for ibiblioteka.lt — Lithuanian National Library (LIBIS) JSON API.

Two entry points:

``parse_ibiblioteka_search_response(json_text)``
    Parses the POST /detailed-search response. Returns a ``CategoryPageResult``
    whose ``products`` list carries the detail-endpoint URL for each record.
    The discover spider stores these as ``DiscoveredUrlItem`` rows; the scan
    spider fetches each URL and calls ``parse_product_page``.

``parse_product_page(json_text)``
    Parses the GET /bibliographic-records/public/{id} JSON response.
    Returns a ``ProductPageResult`` with structured bibliographic metadata.

Person role codes (UNIMARC relator codes used by LIBIS):
  070  author            730  translator (Vertėjas)
  080  illustrator       550  narrator/speaker (Įgarsintojas)
  220  compiler/editor   600  photographer
  470  interviewee
"""

from __future__ import annotations

import json
import re
from typing import Any

from book_scraper.spiders.parser_types import CategoryPageResult, ProductPageResult

_COVER_BASE = "https://ibiblioteka.lt"

# Author role codes — primary author of the intellectual content.
_AUTHOR_CODES = {"070", "080"}
# Translator role codes.
_TRANSLATOR_CODES = {"730"}
# Narrator / audiobook speaker codes.
_NARRATOR_CODES = {"550"}

# Physical attributes patterns for page count extraction.
_PAGES_RE = re.compile(r"(\d+)\s*(?:p\b|psl\.)")
# Duration pattern for audiobooks: "9 val., 25 min., 1 sek."
_DURATION_RE = re.compile(r"\d+\s*(?:val|min|sek)\.?(?:[^)]*)")

_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def parse_ibiblioteka_search_response(json_text: str) -> CategoryPageResult:
    """Parse a POST /detailed-search response.

    Returns products with all fields extractable from the listing — title,
    year, publisher (parsed from publicationView), format, and LIBIS code
    as SKU. The discover spider emits ShopBookItems directly from these so
    books appear without waiting for the scan phase. The scan phase later
    enriches records with author, ISBN, and cover from the detail endpoint.
    """
    try:
        data: dict[str, Any] = json.loads(json_text)
    except json.JSONDecodeError:
        return {"products": [], "total": None}

    items: list[dict[str, Any]] = data.get("results", {}).get("content") or []
    products = []
    for item in items:
        book_id = item.get("id")
        if not book_id:
            continue

        pub_view: str = item.get("publicationView") or ""
        year, publisher = _parse_publication_view(pub_view)

        pub_format: str | None = item.get("publicationFormat")
        book_type, book_format = _infer_type_and_format(pub_format, "")

        products.append(
            {
                "url": (
                    f"{_COVER_BASE}/metis-api/bibliographic-records/public/{book_id}"
                ),
                "title": item.get("titleView") or item.get("titleFull") or None,
                "sku": item.get("code") or None,
                "year": year,
                "publisher": publisher,
                "type": book_type,
                "format": book_format,
                "is_book_product": True,
                "book_score": 5,
            }
        )
    return {"products": products, "total": None}


def _parse_publication_view(pub_view: str) -> tuple[int | None, str | None]:
    """Parse 'Place : Publisher, Year' into (year, publisher)."""
    year: int | None = None
    publisher: str | None = None
    if not pub_view:
        return year, publisher
    m = _YEAR_RE.search(pub_view)
    if m:
        year = int(m.group(1))
    # Publisher is after the first colon, before the year/comma
    if ":" in pub_view:
        after_colon = pub_view.split(":", 1)[1].strip()
        # Strip trailing year and surrounding punctuation
        pub_clean = _YEAR_RE.sub("", after_colon).rstrip(" ,.()")
        publisher = pub_clean.strip() or None
    return year, publisher


_LIBIS_ROLE_CODES = {
    "070": "author",
    "080": "author",
    "730": "translator",
    "550": "narrator",
    "440": "illustrator",
    "340": "editor",
    "220": "compiler",
}


def _extract_authors_canonical(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Build BookItem.authors list with role + per-role position."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    role_pos: dict[str, int] = {}

    # authorViews — primary author list. Maps to role='author'.
    # LIBIS renamed the name field to `titleLt`; `value`/`name` are kept as
    # fallbacks because the checked-in fixtures were captured before that.
    for av in raw.get("authorViews") or []:
        name = av.get("titleLt") or av.get("value")
        code = av.get("code")
        if not name:
            continue
        key = ("author", code or name)
        if key in seen:
            continue
        seen.add(key)
        pos = role_pos.get("author", 0)
        out.append(
            {"name": name, "libis_code": code, "role": "author", "position": pos}
        )
        role_pos["author"] = pos + 1

    # persons[] — multi-role contributors via UNIMARC type codes.
    for person in raw.get("persons") or []:
        name = person.get("titleLt") or person.get("name")
        code = person.get("code")
        if not name:
            continue
        for t in person.get("types") or []:
            role = _LIBIS_ROLE_CODES.get(t.get("code", ""))
            if not role:
                continue
            key = (role, code or name)
            if key in seen:
                continue
            seen.add(key)
            pos = role_pos.get(role, 0)
            out.append(
                {"name": name, "libis_code": code, "role": role, "position": pos}
            )
            role_pos[role] = pos + 1

    return out


def rewrite_scan_url(url: str) -> dict[str, Any]:
    """Ask the detail endpoint for JSON explicitly.

    The endpoint content-negotiates: with the browser ``Accept`` that
    ``HttpxMiddleware`` injects on every request it serves the SPA shell
    (30,995 bytes of xhtml on record 2097094), and with
    ``application/json`` it serves the record (19,593 bytes). Without this
    hook the scan phase fetches 200s the parser finds no title in, so a
    run reports ``completed`` having stored nothing.

    The URL is returned unchanged — only the header matters here.
    """
    return {"url": url, "headers": {"Accept": "application/json"}}


def parse_product_page(json_text: str) -> dict[str, Any]:
    """Parse GET /bibliographic-records/public/{id} JSON response.

    Returns BookItem-shaped dict tagged with ``_emit_as: "book"``. The scan
    spider branches on this sentinel and constructs ``BookItem`` instead of
    ``ShopBookItem``. Keeps ``is_book_product=True`` so scan's classification
    check passes.
    """
    try:
        raw: dict[str, Any] = json.loads(json_text)
    except json.JSONDecodeError:
        return _empty_result()

    physical: str = raw.get("allPhysicalAttributes") or ""
    pub_format: str | None = raw.get("publicationFormat")
    book_type, _ = _infer_type_and_format(pub_format, physical)

    pages: int | None = None
    duration: str | None = None
    if physical:
        if book_type == "audio":
            dur_m = _DURATION_RE.search(physical)
            duration = dur_m.group(0).strip().rstrip(",;") if dur_m else None
        else:
            pg_m = _PAGES_RE.search(physical)
            pages = int(pg_m.group(1)) if pg_m else None

    cover: str | None = raw.get("coverUrl")
    if cover and cover.startswith("/"):
        cover = _COVER_BASE + cover

    pub_date: str | None = raw.get("publicationDate")
    year: int | None = None
    if pub_date:
        m = _YEAR_RE.search(pub_date)
        if m:
            year = int(m.group(1))

    isbns_raw: list[str] = raw.get("isbn") or []
    isbns: list[dict[str, str]] = []
    for raw_isbn in isbns_raw:
        if not raw_isbn:
            continue
        cleaned = raw_isbn.replace("-", "").replace(" ", "")
        isbn_type = (
            "isbn13"
            if len(cleaned) == 13
            else "isbn10"
            if len(cleaned) == 10
            else "unknown"
        )
        isbns.append({"isbn": raw_isbn, "type": isbn_type})

    languages_raw = raw.get("languages") or []
    language = languages_raw[0].get("code") if languages_raw else None
    translated_from = [
        lang.get("code")
        for lang in (raw.get("translatedFromLanguages") or [])
        if lang.get("code")
    ] or None

    audience_raw = raw.get("audience") or []
    audience = audience_raw[0].get("nameLt") if audience_raw else None

    rate_avg = raw.get("rateAverage")
    rate_num = raw.get("rateNumber")

    # Multipart works (e.g. "Ana Karenina T.1 + T.2") are exposed by iBiblioteka
    # as a parent record whose `parts[]` lists each volume's libis_code. The
    # parent carries the "set" ISBN; per-volume ISBNs only show up when you
    # fetch the part records directly. Without recursing into parts, the
    # canonical books table is missing every volume-level ISBN — shop ISBNs
    # for individual volumes (e.g. pegasas "Ana Karenina II" with ISBN
    # 9789955088639 → libis C1B0000814702) can never match. Emit the part
    # URLs so the scan spider can queue them as separate scrape items; each
    # part will be ingested as its own canonical book via the same path.
    part_urls: list[str] = []
    parts_raw = raw.get("parts") or []
    if raw.get("multipart") and parts_raw:
        for part in parts_raw:
            part_code = part.get("code") if isinstance(part, dict) else None
            if part_code:
                part_urls.append(
                    f"{_COVER_BASE}/metis-api/bibliographic-records/public/{part_code}"
                )

    return {
        "_emit_as": "book",
        "_part_urls": part_urls,
        "is_book_product": True,
        "book_score": 5,
        "book_score_reasons": [{"reason": "ibiblioteka_national_library"}],
        "data_source": "ibiblioteka",
        "libis_code": raw.get("code"),
        "title": raw.get("title") or None,
        "title_full": raw.get("titleFull") or None,
        "year": year,
        "publisher": raw.get("publisher") or None,
        "series": raw.get("seriesView") or None,
        "release_place": raw.get("releasePlace") or None,
        "type": book_type,
        "format": pub_format,
        "pages": pages,
        "duration": duration,
        "dimensions": _parse_dimensions(physical),
        "language": language,
        "translated_from": translated_from,
        "description": raw.get("summary") or None,
        "cover_url": cover,
        "upcoming_release": bool(raw.get("upcomingRelease")),
        "udc_codes": raw.get("udcSubjectsCodes") or None,
        "subjects": raw.get("rubricSubjectView") or None,
        "audience": audience,
        "libis_rating": float(rate_avg) if rate_avg else None,
        "libis_review_count": int(rate_num) if rate_num else None,
        "isbns": isbns,
        "authors": _extract_authors_canonical(raw),
    }


_DIMENSIONS_RE = re.compile(r"(\d+)\s*cm")


def _parse_dimensions(physical: str | None) -> str | None:
    if not physical:
        return None
    m = _DIMENSIONS_RE.search(physical)
    return f"{m.group(1)} cm" if m else None


def _infer_type_and_format(
    pub_format: str | None, physical: str
) -> tuple[str, str | None]:
    """Map LIBIS publicationFormat + physical attributes to (type, format)."""
    phys_lower = physical.lower()

    if pub_format == "ELECTRONIC":
        # Audio: physical description mentions mp3/audio file
        if any(kw in phys_lower for kw in ("mp3", "audio", "val.,", "min.,")):
            return "audio", "audio"
        # E-book
        return "ebook", "ebook"

    # PRINTED (default): classify by physical description
    if "kietais viršeliais" in phys_lower or "kieti viršeliai" in phys_lower:
        return "book", "Kieti viršeliai"
    if "minkštais viršeliais" in phys_lower or "minkšti viršeliai" in phys_lower:
        return "book", "Minkšti viršeliai"
    return "book", None


def _empty_result() -> ProductPageResult:
    return {
        "title": None,
        "author": None,
        "isbn": None,
        "sku": None,
        "publisher": None,
        "year": None,
        "format": None,
        "price": None,
        "price_original": None,
        "in_stock": None,
        "image_url": None,
        "categories": [],
        "description": None,
        "pages": None,
        "cover_type": None,
        "duration": None,
        "narrator": None,
        "translator": None,
        "schema_types": [],
        "is_book_product": False,
        "book_score": 0,
        "book_score_reasons": [],
        "type": "book",
        "planned_availability_date": None,
        "rating": None,
        "review_count": None,
    }
