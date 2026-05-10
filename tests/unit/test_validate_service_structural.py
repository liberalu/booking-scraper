"""Pure unit tests for ValidateService structural helpers.

These tests cover tokenisation, slug-title mismatch detection, and the
module-level constant. No DB session needed — only module-level helpers
and constants are exercised.
"""

from __future__ import annotations

from book_scraper.services.validate import (
    VALIDATE_STALE_CADENCE_DAYS,
    _should_flag_slug_title,
    _tokenize,
)


def test_tokenize_strips_diacritics() -> None:
    """Diacritic characters are folded away (NFD decomposition, Mn filter)."""
    tokens = _tokenize("Ką šunys galvoja?")
    # Diacritics stripped: 'ką' -> 'ka', 'šunys' -> 'sunys'
    assert "sunys" in tokens
    assert "šunys" not in tokens
    assert "ka" in tokens
    assert "ką" not in tokens


def test_tokenize_splits_on_dash_and_space() -> None:
    """Dash and whitespace both act as token delimiters."""
    tokens = _tokenize("vyresnio-amziaus zmoniu")
    assert tokens == {"vyresnio", "amziaus", "zmoniu"}


def test_tokenize_empty_string_returns_empty_set() -> None:
    """Empty input produces an empty set."""
    assert _tokenize("") == set()


def test_validate_stale_cadence_constant_is_14_days() -> None:
    """VALIDATE_STALE_CADENCE_DAYS must equal 14 (spec §Staleness checks)."""
    assert VALIDATE_STALE_CADENCE_DAYS == 14


def test_slug_title_mismatch_zero_intersection_flags() -> None:
    """Zero-token overlap between slug and title triggers a flag."""
    # slug='istorija-apie-berniuka', title='Kasdienis maistas' — no overlap
    result = _should_flag_slug_title("istorija-apie-berniuka", "Kasdienis maistas")
    assert result is True


def test_slug_title_mismatch_one_overlap_does_not_flag() -> None:
    """At least one shared token means NO mismatch flag."""
    # slug='sapiens-trumpa-zmonijos', title='Sapiens trumpa istorija'
    # 'sapiens' and 'trumpa' overlap (after diacritic strip + lower)
    result = _should_flag_slug_title(
        "sapiens-trumpa-zmonijos", "Sapiens trumpa istorija"
    )
    assert result is False


def test_slug_title_mismatch_handles_lithuanian_diacritics() -> None:
    """Diacritics are stripped before comparing slug and title tokens."""
    # slug 'silko-kelias' vs title 'Šilko kelias'
    # 'silko' == 'silko' after stripping š -> s from title side
    assert _should_flag_slug_title("silko-kelias", "Šilko kelias") is False


def test_slug_title_mismatch_none_slug_does_not_flag() -> None:
    """None slug never flags (no meaningful comparison possible)."""
    assert _should_flag_slug_title(None, "Some title") is False


def test_slug_title_mismatch_none_title_does_not_flag() -> None:
    """None title never flags."""
    assert _should_flag_slug_title("some-slug", None) is False
