from book_scraper.isbn import normalize_isbn, to_isbn10, to_isbn13


def test_to_isbn13_from_isbn10():
    assert to_isbn13("0306406152") == "9780306406157"


def test_to_isbn13_from_already_13():
    assert to_isbn13("9780306406157") == "9780306406157"


def test_to_isbn13_strips_dashes():
    assert to_isbn13("0-306-40615-2") == "9780306406157"


def test_to_isbn10_from_isbn13_with_978_prefix():
    assert to_isbn10("9780306406157") == "0306406152"


def test_to_isbn10_returns_none_for_979_prefix():
    """ISBN-13s starting with 979 have no ISBN-10 equivalent."""
    assert to_isbn10("9791234567896") is None


def test_to_isbn10_from_already_10_returns_normalized():
    assert to_isbn10("0306406152") == "0306406152"


def test_to_isbn10_handles_x_check_digit():
    # Refactoring by Fowler — ISBN-13 9780201616224, ISBN-10 020161622X
    assert to_isbn10("9780201616224") == "020161622X"


def test_normalize_isbn_strips_dashes_and_spaces():
    assert normalize_isbn("978-0-306-40615-7") == "9780306406157"
    assert normalize_isbn("978 0 306 40615 7") == "9780306406157"
