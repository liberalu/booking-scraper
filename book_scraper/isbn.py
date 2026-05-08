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
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(cleaned))
        return total % 10 == 0
    if _ISBN_10_RE.match(cleaned):
        total = sum(
            (10 if c in "Xx" else int(c)) * (10 - i) for i, c in enumerate(cleaned)
        )
        return total % 11 == 0
    return False


def to_isbn13(raw: str | None) -> str | None:
    """Return the ISBN-13 form of an ISBN. Returns None on invalid input."""
    cleaned = normalize_isbn(raw)
    if not cleaned:
        return None
    if _ISBN_13_RE.match(cleaned):
        return cleaned
    if _ISBN_10_RE.match(cleaned):
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
