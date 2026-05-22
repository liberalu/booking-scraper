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


# ---------------------------------------------------------------------------
# _looks_diacritic_lossy — detects shop-side slug generators that drop
# Lithuanian diacritics character-by-character instead of transliterating.
# Real-world trigger: pegasas "Kalėdų pūga" → "kale-du-pu-ga-2196148".
# ---------------------------------------------------------------------------


def test_diacritic_lossy_flags_kaledu_puga() -> None:
    """The pegasas reference case: title 'Kalėdų pūga' (2 words) emits
    slug 'kale-du-pu-ga' (4 pieces) because each diacritic is dropped
    instead of transliterated. 4 > 2 → flag."""
    from book_scraper.services.validate import _looks_diacritic_lossy

    assert _looks_diacritic_lossy("kale-du-pu-ga-2196148", "Kalėdų pūga") is True


def test_diacritic_lossy_handles_nfd_decomposed_title() -> None:
    """The DB stores titles in NFD form: 'Kalėdų pūga' is actually
    'Kale' + U+0307 + 'du' + U+0328 + ' ' + 'pu' + U+0304 + 'ga'.

    Without NFC normalisation, the diacritic-membership check fails AND
    the title-word regex treats each combining mark as a word boundary —
    counting 4 'words' instead of 2 and masking the bug. The helper must
    NFC-normalise before comparing.

    This bug shipped to production; only manual DB-level testing exposed
    it. The fixture here is the actual byte sequence from the database.
    """
    import unicodedata

    from book_scraper.services.validate import _looks_diacritic_lossy

    # Explicitly normalise to NFD at runtime so the test fixture is the
    # actual decomposed byte sequence the DB stores, regardless of how
    # the source-file editor encodes string literals (some editors
    # silently NFC-coerce).
    title_nfd = unicodedata.normalize("NFD", "Kalėdų pūga")
    assert any(
        unicodedata.category(c) == "Mn" for c in title_nfd
    ), "NFD normalisation produced no combining marks — fixture broken"
    assert _looks_diacritic_lossy("kale-du-pu-ga-2196148", title_nfd) is True


def test_diacritic_lossy_skips_when_title_has_no_diacritics() -> None:
    """The gate prevents flagging slugs of abbreviation-heavy products
    (e.g. 'asus-rog-strix-2024' for 'Asus ROG Strix 2024')."""
    from book_scraper.services.validate import _looks_diacritic_lossy

    assert _looks_diacritic_lossy("asus-rog-strix-2024", "Asus ROG Strix") is False
    assert _looks_diacritic_lossy("a-b-c-d-1234", "A B C D") is False


def test_diacritic_lossy_skips_legit_short_word_titles() -> None:
    """Multi-word titles with naturally short words (e.g. 'Tu. Aš. Mes',
    'Kerstina ir aš') produce a slug with one piece per word — the
    count-comparison must not flag these."""
    from book_scraper.services.validate import _looks_diacritic_lossy

    # 3 words → 3 slug pieces → not flagged
    assert _looks_diacritic_lossy("tu-as-mes-2187493", "Tu. Aš. Mes") is False
    assert _looks_diacritic_lossy("kerstina-ir-as-2124079", "Kerstina ir aš") is False
    assert _looks_diacritic_lossy("kodel-gi-ne-22417759", "Kodėl gi ne") is False


def test_diacritic_lossy_skips_correct_transliteration() -> None:
    """When the shop's slug generator does the right thing
    ('Kalėdų pūga' → 'kaledu-puga'), no flag."""
    from book_scraper.services.validate import _looks_diacritic_lossy

    assert _looks_diacritic_lossy("kaledu-puga-2196148", "Kalėdų pūga") is False


def test_diacritic_lossy_skips_short_slug() -> None:
    """Below 3 alphabetic pieces, the bug pattern cannot manifest
    (the title needs ≥2 multi-syllable diacritic words). Reject the
    count-comparison noise."""
    from book_scraper.services.validate import _looks_diacritic_lossy

    assert _looks_diacritic_lossy("kaledu-puga", "Kalėdų") is False
    assert _looks_diacritic_lossy("a-b-1234", "Žinianešys") is False


def test_diacritic_lossy_handles_none() -> None:
    from book_scraper.services.validate import _looks_diacritic_lossy

    assert _looks_diacritic_lossy(None, "Kalėdų pūga") is False
    assert _looks_diacritic_lossy("kale-du-pu-ga", None) is False
    assert _looks_diacritic_lossy("", "") is False


# ---------------------------------------------------------------------------
# _title_indicates_non_book — parenthesised format markers and bundle words
# ---------------------------------------------------------------------------


def test_title_indicates_non_book_detects_media_formats() -> None:
    """Parenthesised format markers trigger the non-book signal."""
    from book_scraper.services.validate import _title_indicates_non_book

    assert _title_indicates_non_book("Filmas (DVD)") is True
    assert _title_indicates_non_book("Muzika (CD)") is True
    assert _title_indicates_non_book("Kūrinys (Blu-ray)") is True
    assert _title_indicates_non_book("Rinkinys (USB)") is True
    assert _title_indicates_non_book("Albumas (Vinyl)") is True
    assert _title_indicates_non_book("Knyga (MP3)") is True
    assert _title_indicates_non_book("Filmas (VHS)") is True


def test_title_indicates_non_book_detects_bundles() -> None:
    """Bundle / set keywords trigger the non-book signal."""
    from book_scraper.services.validate import _title_indicates_non_book

    assert _title_indicates_non_book("Mokomasis rinkinys") is True
    assert _title_indicates_non_book("Vadovėlių komplektas") is True


def test_title_indicates_non_book_false_negative_guard() -> None:
    """'(su DVD)' and similar book-with-media combos must NOT be flagged.

    A book that includes a DVD or CD as a supplement (common Lithuanian
    educational titles) is still a book.  Only the bare format marker
    '(DVD)' in parentheses — without a Lithuanian preposition — triggers
    the non-book signal.
    """
    from book_scraper.services.validate import _title_indicates_non_book

    # These are books that come bundled with media — must pass through.
    assert _title_indicates_non_book("Anglų kalba su CD") is False
    assert _title_indicates_non_book("Matematika (su DVD)") is False
    assert _title_indicates_non_book("Fizika (su CD)") is False
    assert _title_indicates_non_book("Chemija su Blu-ray") is False

    # Plain book titles must not trigger.
    assert _title_indicates_non_book("Lietuvių kalbos vadovėlis") is False
    assert _title_indicates_non_book(None) is False
    assert _title_indicates_non_book("") is False


# ---------------------------------------------------------------------------
# _categories_indicate_non_book — keyword search across LT category names
# for non-book products (toys, chocolate, stationery, etc.)
# ---------------------------------------------------------------------------


def test_categories_non_book_detects_toys() -> None:
    """Žaislai / žaidimai / dėlionės etc. trigger the non-book signal."""
    from book_scraper.services.validate import _categories_indicate_non_book

    assert _categories_indicate_non_book(["Žaislai", "Vaikams"]) is True
    assert _categories_indicate_non_book(["Stalo žaidimai"]) is True
    assert _categories_indicate_non_book(["Dėlionės ir konstruktoriai"]) is True


def test_categories_non_book_detects_stationery() -> None:
    """Sąsiuviniai / raštinės / popieriaus etc. trigger the non-book signal."""
    from book_scraper.services.validate import _categories_indicate_non_book

    assert _categories_indicate_non_book(["Mokyklinės sąsiuviniai"]) is True
    assert _categories_indicate_non_book(["Raštinės reikmenys"]) is True
    assert _categories_indicate_non_book(["Popieriaus gaminiai"]) is True


def test_categories_non_book_case_and_diacritic_insensitive() -> None:
    """The keyword check must be both case- and diacritic-insensitive,
    because LT category names appear in mixed case and Lithuanian shops
    sometimes drop diacritics in metadata."""
    from book_scraper.services.validate import _categories_indicate_non_book

    assert _categories_indicate_non_book(["ZAISLAI"]) is True       # no diacritic, uppercase
    assert _categories_indicate_non_book(["zaislai"]) is True       # no diacritic, lowercase
    assert _categories_indicate_non_book(["Žaislai"]) is True       # with diacritic


def test_categories_non_book_does_not_flag_book_categories() -> None:
    """Genuine book category names must not be flagged."""
    from book_scraper.services.validate import _categories_indicate_non_book

    assert _categories_indicate_non_book(["Grožinė literatūra"]) is False
    assert _categories_indicate_non_book(["Detektyvai", "Romanai"]) is False
    assert _categories_indicate_non_book(["Vaikų literatūra"]) is False


def test_categories_non_book_handles_none_and_empty() -> None:
    from book_scraper.services.validate import _categories_indicate_non_book

    assert _categories_indicate_non_book(None) is False
    assert _categories_indicate_non_book([]) is False


# ---------------------------------------------------------------------------
# _is_genuine_url_alias — filters URL-encoding mismatches and OpenCart
# legacy route URLs (platform-level aliases, not data-quality issues).
# ---------------------------------------------------------------------------


def test_url_alias_filters_percent_encoded_lithuanian() -> None:
    """The canonical URL has percent-encoded Lithuanian chars; the alias
    has the decoded form. URL-decoded they're identical → not a genuine
    alias."""
    from book_scraper.services.validate import _is_genuine_url_alias

    canon = "https://vaga.lt/mi%C5%A1ku-bastunai-2-pavojinga-draugyste"
    alias = "https://vaga.lt/mišku-bastunai-2-pavojinga-draugyste"
    assert _is_genuine_url_alias(canon, alias) is False


def test_url_alias_filters_opencart_route_form() -> None:
    """vaga.lt's underlying OpenCart platform exposes every product at
    both a SEO slug and an `index.php?route=product/product&product_id=`
    URL. Both URL shapes coexist by design and aren't data-quality
    issues."""
    from book_scraper.services.validate import _is_genuine_url_alias

    canon = "https://vaga.lt/uzrasu-knygele-lotus-river-ultra-flexi"
    alias = "https://vaga.lt/index.php?route=product/product&product_id=179009"
    assert _is_genuine_url_alias(canon, alias) is False
    # And the percent-encoded slash variant.
    alias_encoded = "https://vaga.lt/index.php?route=product%2Fproduct&product_id=179009"
    assert _is_genuine_url_alias(canon, alias_encoded) is False


def test_url_alias_keeps_genuinely_different_slugs() -> None:
    """When two truly different slugs both point at the same shop_book
    (e.g. duplicate product IDs or edition variants), the alias is real
    and should be flagged."""
    from book_scraper.services.validate import _is_genuine_url_alias

    canon = "https://vaga.lt/leliukes-178029"
    alias = "https://vaga.lt/leliukes-178026"
    assert _is_genuine_url_alias(canon, alias) is True
    # Year difference between editions:
    canon2 = "https://vaga.lt/jaunasis-pianistas-2025"
    alias2 = "https://vaga.lt/jaunasis-pianistas-2026"
    assert _is_genuine_url_alias(canon2, alias2) is True


def test_url_alias_filters_trailing_slash_only() -> None:
    """A trailing slash mismatch isn't an alias (already handled in the
    SQL gate, but the Python helper should agree)."""
    from book_scraper.services.validate import _is_genuine_url_alias

    canon = "https://www.pegasas.lt/foo-1234"
    alias = "https://www.pegasas.lt/foo-1234/"
    assert _is_genuine_url_alias(canon, alias) is False


def test_url_alias_handles_empty_inputs() -> None:
    from book_scraper.services.validate import _is_genuine_url_alias

    assert _is_genuine_url_alias("", "https://vaga.lt/x") is False
    assert _is_genuine_url_alias("https://vaga.lt/x", "") is False
