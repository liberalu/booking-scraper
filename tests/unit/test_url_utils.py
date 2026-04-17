import pytest

from book_scraper.url_utils import normalize_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Lowercases scheme + host
        ("HTTPS://Vaga.LT/Book", "https://vaga.lt/Book"),
        # Drops fragment
        ("https://vaga.lt/book#section", "https://vaga.lt/book"),
        # Strips utm_* params
        (
            "https://vaga.lt/book?utm_source=x&utm_medium=y",
            "https://vaga.lt/book",
        ),
        # Strips known tracking exacts, keeps real query params
        (
            "https://vaga.lt/book?fbclid=abc&size=large",
            "https://vaga.lt/book?size=large",
        ),
        # Strips trailing slash (non-root)
        ("https://vaga.lt/book/", "https://vaga.lt/book"),
        # Keeps root slash
        ("https://vaga.lt/", "https://vaga.lt/"),
        # Empty path becomes root
        ("https://vaga.lt", "https://vaga.lt/"),
        # Collapses duplicate slashes in path
        ("https://vaga.lt//a//b/", "https://vaga.lt/a/b"),
        # Preserves path case
        ("https://vaga.lt/BookTitle", "https://vaga.lt/BookTitle"),
        # Whitespace trimming
        ("  https://vaga.lt/book  ", "https://vaga.lt/book"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_normalize_url_is_idempotent() -> None:
    url = "https://vaga.lt/book?utm_source=x&real=1#frag"
    once = normalize_url(url)
    twice = normalize_url(once)
    assert once == twice
