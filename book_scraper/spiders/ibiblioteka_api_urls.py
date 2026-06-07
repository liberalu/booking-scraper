"""URL/body helpers for the ibiblioteka.lt national library JSON API.

The search endpoint is a POST with a JSON body. Like the LupaSearch helper,
we encode all request parameters into a synthetic URL's query string so the
DB-backed queue can store and resume them as plain strings.

Endpoint note (2026-06): the LIBIS frontend split the search endpoint. The
bare ``…/public/detailed-search`` path now answers ``405 Method Not Allowed``
to POST; paginated results moved to ``…/public/detailed-search/page`` (still
POST, same response shape: ``{"results": {"content": [...]}}``). The body
schema also expanded — ``selectedFilters`` now requires the full key set the
SPA sends or the endpoint returns ``400 Bad request``. Both are reflected
below. Pagination is still driven by ``pageStartIndex`` (not the ``page``
field), so the monthly-band + psi-advance scheme is unchanged.

Synthetic URL format (current — monthly bands):
  https://ibiblioteka.lt/metis-api/bibliographic-records/public/detailed-search/page
  ?psi=0&ps=100&df=2024-01-01&dt=2024-02-01

Parameters:
  psi  pageStartIndex (0-based offset into result set)
  ps   pageSize (minimum 10, maximum 500)
  df   date_from — ISO date string, lower bound (inclusive)
  dt   date_to   — ISO date string, upper bound (exclusive)

Legacy format (annual bands — still accepted for backward compat with
any already-queued URLs):
  ?psi=0&ps=100&yf=2024&yt=2025

Why monthly bands?  The API hard-caps results at pageStartIndex ~9,900 per
search.  High-volume years (e.g. 2009, 2020) have >9,900 books, so annual
bands silently truncate them.  Monthly bands average ~800 records/month,
leaving ample headroom below the cap.

Why no language filter?  The previous code sent ``languages: [Lithuanian]``
which excluded foreign-language books published in Lithuania (Russian-language
textbooks, English-language academic works, etc.).  ibiblioteka catalogues all
books in the Lithuanian national library regardless of content language, and
Lithuanian bookshops carry those books — so we want them all.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from book_scraper.config_models import IbibliotekaApiConfig

_ENDPOINT = (
    "https://ibiblioteka.lt/metis-api/bibliographic-records/public/detailed-search/page"
)

# Static body fields shared by every search request. Mirrors the payload the
# LIBIS SPA POSTs to …/detailed-search/page (2026-06 schema). The full
# selectedFilters key set is mandatory — dropping any key yields 400. Per-band
# fields (pageStartIndex, pageSize, publicationDateRange) are layered on top in
# build_ibiblioteka_post_request_kwargs.
_FIXED_BODY: dict[str, Any] = {
    "hierarchicalListMode": False,
    "selectedFilters": {
        "audiences": [],
        "authors": [],
        "languages": [],
        "typeFilter": [],
        "subjects": [],
        "sources": [],
        "libraries": [],
        "releaseStatus": [],
        "rateAverages": [],
        "accessibleOnline": [],
        "accessiblePublications": [],
        "accessibilityFeatures": [],
        "mediaProperties": [],
        "recordStatuses": [],
        "dateRange": {},
    },
    "searchFields": [],
    "librariesData": [
        {
            "bookReceivedDateTypeEnumLastTwoWeeks": False,
            "bookReceivedDateTypeEnumLastMonth": False,
            "bookReceivedDateTypeEnumLastThreeMonths": False,
            "bookReceivedDateTypeEnumLastSixMonths": False,
            "bookReceivedDateTypeEnumLastYear": False,
            "bookReceivedDateTypes": [],
        }
    ],
    "publicationTypes": ["BOOK"],
    "publicationAttributes": [],
    "serialPublicationTypes": [],
    "publicationFormats": [],
    "rubricSubjects": [],
    "audiences": [],
    "udcSubjects": [],
    "articleSubjects": [],
    "publicationCountries": [],
    "translateFromLanguages": [],
    "page": 0,
    "sortBy": "MATCH",
    "recentlySearchedByFilters": False,
    "accessiblePublications": [],
    "accessibilityType": [],
    "informationAccessibilityMethod": [],
    "accessibilityFeatures": [],
    "accessibilityHazards": [],
    "contentManagement": [],
}


def build_ibiblioteka_seed_urls(conf: IbibliotekaApiConfig) -> list[str]:
    """One synthetic seed URL per calendar month in [year_from, year_to).

    Monthly bands keep each band well below the server's 9,900-record cap
    (annual bands hit the cap for high-volume years and silently drop books).
    Each seed starts at pageStartIndex=0.
    """
    urls = []
    current = date(conf.year_from, 1, 1)
    end = date(conf.year_to, 1, 1)  # exclusive upper bound
    while current < end:
        if current.month == 12:
            nxt = date(current.year + 1, 1, 1)
        else:
            nxt = date(current.year, current.month + 1, 1)
        params = [
            ("psi", "0"),
            ("ps", str(conf.page_size)),
            ("df", current.isoformat()),
            ("dt", nxt.isoformat()),
        ]
        urls.append(_ENDPOINT + "?" + urlencode(params))
        current = nxt
    return urls


def parse_ibiblioteka_url_params(url: str) -> tuple[int, int, str, str]:
    """Return (psi, ps, date_from, date_to) from a synthetic ibiblioteka URL.

    Accepts both the current ``df``/``dt`` format and the legacy ``yf``/``yt``
    format so that any already-queued annual URLs continue to work.
    """
    qs = parse_qs(urlparse(url).query)
    psi = int(qs.get("psi", ["0"])[0])
    ps = int(qs.get("ps", ["100"])[0])

    if "df" in qs and "dt" in qs:
        date_from = qs["df"][0]
        date_to = qs["dt"][0]
    else:
        # Legacy annual format: yf=2024&yt=2025
        yf = int(qs.get("yf", ["2020"])[0])
        yt = int(qs.get("yt", ["2021"])[0])
        date_from = f"{yf}-01-01"
        date_to = f"{yt}-01-01"

    return psi, ps, date_from, date_to


def advance_ibiblioteka_url(url: str, new_psi: int) -> str:
    """Return the same URL with ``psi`` replaced by ``new_psi``."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    qs["psi"] = [str(new_psi)]
    flat: list[tuple[str, str]] = []
    # Preserve whichever date-range format is present in the original URL.
    for key in ("psi", "ps", "df", "dt", "yf", "yt"):
        if key in qs:
            flat.append((key, qs[key][0]))
    return urlunparse(parsed._replace(query=urlencode(flat)))


def build_ibiblioteka_post_request_kwargs(url: str) -> dict[str, Any]:
    """Reconstruct the POST body + headers from a synthetic ibiblioteka URL."""
    psi, ps, date_from, date_to = parse_ibiblioteka_url_params(url)
    body_obj = {
        **_FIXED_BODY,
        "pageStartIndex": psi,
        "pageSize": ps,
        "publicationDateRange": {
            "from": f"{date_from}T00:00:00.000Z",
            "to": f"{date_to}T00:00:00.000Z",
        },
        "languages": [],  # No language filter — include all languages.
    }
    body = json.dumps(body_obj, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-GB,en;q=0.5",
    }
    return {"method": "POST", "body": body, "headers": headers}
