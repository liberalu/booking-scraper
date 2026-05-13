"""Unit tests for the ISBN-shape detection used by the books search."""
from book_scraper.dashboard.queries import _looks_like_isbn


def test_isbn13_plain():
    assert _looks_like_isbn("9786094661099") == "9786094661099"


def test_isbn13_with_dashes():
    assert _looks_like_isbn("978-609-466-1099") == "9786094661099"


def test_isbn13_with_spaces():
    assert _looks_like_isbn("978 609 466 1099") == "9786094661099"


def test_isbn10_plain():
    assert _looks_like_isbn("0316769487") == "0316769487"


def test_isbn10_with_x_check_digit():
    assert _looks_like_isbn("097522980X") == "097522980X"


def test_isbn10_with_lowercase_x_uppercased():
    assert _looks_like_isbn("097522980x") == "097522980X"


def test_too_short_returns_none():
    assert _looks_like_isbn("123456") is None


def test_too_long_returns_none():
    assert _looks_like_isbn("12345678901234") is None


def test_alpha_returns_none():
    assert _looks_like_isbn("Tolkien") is None


def test_mixed_alpha_digits_returns_none():
    assert _looks_like_isbn("abc12345678") is None


def test_empty_returns_none():
    assert _looks_like_isbn("") is None


def test_whitespace_only_returns_none():
    assert _looks_like_isbn("   ") is None
