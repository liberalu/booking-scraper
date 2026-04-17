from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_EXACT = frozenset(
    {
        "fbclid",
        "gclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "_ga",
        "yclid",
        "ref",
        "ref_src",
        "ref_url",
    }
)


def _is_tracking(key: str) -> bool:
    lower = key.lower()
    if any(lower.startswith(p) for p in _TRACKING_PREFIXES):
        return True
    return lower in _TRACKING_EXACT


def _collapse_slashes(path: str) -> str:
    if "//" not in path:
        return path
    out: list[str] = []
    prev_slash = False
    for ch in path:
        if ch == "/":
            if not prev_slash:
                out.append(ch)
            prev_slash = True
        else:
            out.append(ch)
            prev_slash = False
    return "".join(out)


def normalize_url(url: str) -> str:
    """Canonicalise a URL for stable equality and uniqueness.

    Lowercases scheme+host, drops fragments, strips tracking params,
    collapses duplicate slashes, and trims a trailing slash (except
    on the root). Path case is preserved because shops often treat
    paths as case-sensitive.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()

    path = _collapse_slashes(parts.path) or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not _is_tracking(k)
        ]
    )

    return urlunsplit((scheme, netloc, path, query, ""))
