"""Closed set of `shop_book.type` values, mirrored from the Postgres
`shop_book_type` enum in [book_scraper/db/models.py].

A typo on the Python side silently demotes a row to `non_book` (or trips
the DB enum write); pinning the alphabet here lets mypy catch that at
the seams."""

from typing import Literal

BookType = Literal["book", "audio", "ebook", "non_book"]

BOOK_TYPES: tuple[BookType, ...] = ("book", "audio", "ebook", "non_book")
