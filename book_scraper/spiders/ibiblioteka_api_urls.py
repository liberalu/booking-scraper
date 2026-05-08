"""URL/body helpers for the ibiblioteka.lt national library JSON API.

The search endpoint is a POST with a JSON body. Like the LupaSearch helper,
we encode all request parameters into a synthetic URL's query string so the
DB-backed queue can store and resume them as plain strings.

Synthetic URL format:
  https://ibiblioteka.lt/metis-api/bibliographic-records/public/detailed-search
  ?psi=0&ps=100&yf=2024&yt=2025

Parameters:
  psi  pageStartIndex (0-based offset into result set)
  ps   pageSize (minimum 10, maximum 500)
  yf   year_from — publication year lower bound (inclusive)
  yt   year_to   — publication year upper bound (exclusive, i.e. next year)
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from book_scraper.config_models import IbibliotekaApiConfig

_ENDPOINT = (
    "https://ibiblioteka.lt"
    "/metis-api/bibliographic-records/public/detailed-search"
)

_LT_LANGUAGE = {
    "id": "116398",
    "code": "lit",
    "nameLt": "lietuvių",
    "nameEn": "Lithuanian",
}

_FIXED_BODY: dict[str, Any] = {
    "hierarchicalListMode": False,
    "selectedFilters": {
        "audiences": [], "authors": [], "languages": [],
        "publicationFormats": [], "publicationTypes": [],
        "serialPublicationTypes": [], "subjects": [], "sources": [],
        "libraries": [], "releaseStatus": [], "rateAverages": [],
        "accessibleOnline": [],
    },
    "searchFields": [
        {
            "logicalOperator": "AND",
            "searchField": "TITLE",
            "phraseMatch": "ALL_WORDS",
            "keywords": [],
            "searchPhrase": "",
        }
    ],
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
    "page": 1,
    "sortBy": "MATCH",
    "customFilter": False,
    "recentlySearchedByFilters": False,
}


def build_ibiblioteka_seed_urls(conf: IbibliotekaApiConfig) -> list[str]:
    """One synthetic seed URL per year in [year_from, year_to).

    Each seed starts at pageStartIndex=0 so the spider's first-page handler
    can enqueue subsequent pages for that year band concurrently.
    """
    urls = []
    for year in range(conf.year_from, conf.year_to):
        params = [
            ("psi", "0"),
            ("ps", str(conf.page_size)),
            ("yf", str(year)),
            ("yt", str(year + 1)),
        ]
        urls.append(_ENDPOINT + "?" + urlencode(params))
    return urls


def parse_ibiblioteka_url_params(url: str) -> tuple[int, int, int, int]:
    """Return (psi, ps, yf, yt) from a synthetic ibiblioteka URL."""
    qs = parse_qs(urlparse(url).query)
    psi = int(qs.get("psi", ["0"])[0])
    ps = int(qs.get("ps", ["100"])[0])
    yf = int(qs.get("yf", ["2020"])[0])
    yt = int(qs.get("yt", ["2021"])[0])
    return psi, ps, yf, yt


def advance_ibiblioteka_url(url: str, new_psi: int) -> str:
    """Return the same URL with `psi` replaced by `new_psi`."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    qs["psi"] = [str(new_psi)]
    flat: list[tuple[str, str]] = []
    for key in ("psi", "ps", "yf", "yt"):
        if key in qs:
            flat.append((key, qs[key][0]))
    return urlunparse(parsed._replace(query=urlencode(flat)))


def build_ibiblioteka_post_request_kwargs(url: str) -> dict[str, Any]:
    """Reconstruct the POST body + headers from a synthetic ibiblioteka URL."""
    psi, ps, yf, yt = parse_ibiblioteka_url_params(url)
    body_obj = {
        **_FIXED_BODY,
        "pageStartIndex": psi,
        "pageSize": ps,
        "publicationDateRange": {
            "from": f"{yf}-01-01T00:00:00.000Z",
            "to": f"{yt}-01-01T00:00:00.000Z",
        },
        "languages": [_LT_LANGUAGE],
    }
    body = json.dumps(body_obj, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-GB,en;q=0.5",
    }
    return {"method": "POST", "body": body, "headers": headers}
