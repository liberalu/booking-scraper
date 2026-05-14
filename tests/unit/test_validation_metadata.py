from book_scraper.dashboard.queries import ISSUE_DESCRIPTIONS, ISSUE_SEVERITY


def test_field_missing_removed_from_metadata() -> None:
    assert "field_missing" not in ISSUE_DESCRIPTIONS
    assert "field_missing" not in ISSUE_SEVERITY


def test_all_issue_types_use_known_severity() -> None:
    """Severities are bounded — UI maps them to color tones."""
    assert set(ISSUE_SEVERITY.values()) <= {"critical", "warning", "info"}
