import re

_ISBN_13_RE = re.compile(r"^97[89]\d{10}$")
_ISBN_10_RE = re.compile(r"^\d{9}[\dXx]$")


def normalize_isbn(raw: str | None) -> str:
    if not raw:
        return ""
    return raw.replace("-", "").replace(" ", "")


def is_valid_isbn(raw: str | None) -> bool:
    cleaned = normalize_isbn(raw)
    if _ISBN_13_RE.match(cleaned):
        # Reject the exact double-prefix corruption signature:
        # `9789789...` or `9799789...`. This is the fingerprint of a
        # 10-digit value beginning with "978"/"979" that was wrongly
        # treated as an ISBN-10 and converted to ISBN-13 by prepending
        # another "978" — the resulting checksum is computed correctly
        # by accident, but no real registered ISBN group identifier
        # starts with "9789" or "9799" (those subranges contain the
        # EAN prefixes themselves, not group IDs).
        if cleaned[:7] in ("9789789", "9799789", "9789979", "9799979"):
            return False
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(cleaned))
        return total % 10 == 0
    if _ISBN_10_RE.match(cleaned):
        # 10-digit values starting with "978"/"979" aren't valid ISBN-10
        # — those are EAN prefixes, not ISBN-10 group identifiers.
        if cleaned[:3] in ("978", "979"):
            return False
        total = sum(
            (10 if c in "Xx" else int(c)) * (10 - i) for i, c in enumerate(cleaned)
        )
        return total % 11 == 0
    return False


def to_isbn13(raw: str | None) -> str | None:
    """Return the ISBN-13 form of an ISBN. Returns None on invalid input.

    A 10-digit value starting with "978" or "979" is NOT a valid ISBN-10
    — those prefixes are the EAN Bookland prefixes added with the
    migration to ISBN-13 and don't appear as ISBN-10 group identifiers.
    Treating such a value as ISBN-10 produces a "978978…" double-prefix
    garbage ISBN-13 (e.g. raw `9789955084` → `9789789955084`). Reject
    them outright so callers see `None` and can flag as `invalid_isbn`
    rather than propagating corruption.
    """
    cleaned = normalize_isbn(raw)
    if not cleaned:
        return None
    if _ISBN_13_RE.match(cleaned):
        return cleaned
    if _ISBN_10_RE.match(cleaned):
        if cleaned[:3] in ("978", "979"):
            return None
        body = "978" + cleaned[:9]
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(body))
        check = (10 - total % 10) % 10
        return body + str(check)
    return None


def to_isbn10(raw: str | None) -> str | None:
    """Return the ISBN-10 form of an ISBN. Returns None for 979-prefixed
    ISBN-13s (no ISBN-10 equivalent) or invalid input.
    """
    cleaned = normalize_isbn(raw)
    if not cleaned:
        return None
    if _ISBN_10_RE.match(cleaned):
        return cleaned.upper()
    if _ISBN_13_RE.match(cleaned):
        if not cleaned.startswith("978"):
            return None
        body = cleaned[3:12]
        total = sum(int(d) * (10 - i) for i, d in enumerate(body))
        check = (11 - total % 11) % 11
        return body + ("X" if check == 10 else str(check))
    return None
