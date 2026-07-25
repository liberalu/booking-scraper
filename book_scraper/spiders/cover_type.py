"""Cover-type label normaliser.

Maps Lithuanian cover-type labels (and English synonyms) to the canonical
format tokens we store on `shop_books.format`. Lithuanian shops express
cover type with the word "viršeliai" (covers) preceded by an adjective:

  - "kieti viršeliai"   → hardcover
  - "minkšti viršeliai" → paperback
  - "puskiečiai viršeliai" → semi-hardcover (mapped to hardcover)

Each label has a diacritic-stripped variant in the wild ("keti" instead
of "kieti", typos like "keti" or "puskieciai"), and patogupirkti's
"Formatas" field can mix dimensions with cover type in one string
(e.g. "15x22, minkšti viršeliai"). The mapping must therefore:

  1. Be case- and diacritic-insensitive.
  2. Recognise typos like "keti" (missing 'i') as hard cover.
  3. Skip a pure-dimension input (returns None instead of leaking
     "15x22" as a format value — that's what was driving the
     `format_is_dimensions` validator issue, ~1,200 rows on
     patogupirkti).
  4. Handle multi-segment values (split on comma, try each).
"""

from __future__ import annotations

import re
import unicodedata

# Canonical format tokens. Anything outside this set is suspicious and
# downgraded to None so it doesn't leak into shop_books.format.
_CANONICAL_FORMATS: frozenset[str] = frozenset(
    {"hardcover", "paperback", "ebook", "audiobook", "cd", "dvd", "book"}
)

# Pure dimension pattern: catches "15x22", "17 x 24", "170 x 205 mm",
# "21X30 cm", etc. Used to reject dimensions-only segments outright.
_DIMENSION_RE = re.compile(r"^\s*\d+\s*[xX×]\s*\d+(\s*(mm|cm))?\s*$", re.IGNORECASE)


def _strip_diacritics(s: str) -> str:
    """Normalise to NFD and drop combining marks (ė → e, š → s, etc.)."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _map_one_segment(seg: str) -> str | None:
    """Map a single (already-trimmed) value to a canonical format token.

    Returns None when:
    - The segment is empty.
    - The segment is a pure dimension expression.
    - The segment has no recognisable cover-type keyword AND isn't an
      already-canonical token.
    """
    s = seg.strip()
    if not s:
        return None
    if _DIMENSION_RE.match(s):
        return None
    lower = s.lower()
    if lower in _CANONICAL_FORMATS:
        return lower
    stripped = _strip_diacritics(lower)
    # Lithuanian cover-type detection. Match before "viršeliai":
    #   "puskie..." → semi-hard (treated as hardcover for downstream)
    #   "kiet..." / "ket..." → hardcover (handles "keti" typo)
    #   "minkst..." → paperback
    if "puskiet" in stripped or "puskie" in stripped:
        return "hardcover"
    if "kiet" in stripped or re.search(r"\bketi\b", stripped):
        return "hardcover"
    if "minkst" in stripped:
        return "paperback"
    return None


def format_from_cover_type(cover_type: str | None) -> str | None:
    """Map a (possibly-multi-segment) cover-type label to canonical format.

    Iterates comma-separated segments; first segment yielding a canonical
    mapping wins. Returns None when no segment maps to anything known —
    callers should treat that as "format unknown" rather than persisting
    the raw label.
    """
    if not cover_type:
        return None
    for seg in cover_type.split(","):
        mapped = _map_one_segment(seg)
        if mapped:
            return mapped
    return None
