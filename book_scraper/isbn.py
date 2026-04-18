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
