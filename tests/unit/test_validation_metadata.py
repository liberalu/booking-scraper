from book_scraper.dashboard.queries import ISSUE_DESCRIPTIONS, ISSUE_SEVERITY


def test_field_missing_removed_from_metadata() -> None:
    assert "field_missing" not in ISSUE_DESCRIPTIONS
    assert "field_missing" not in ISSUE_SEVERITY


def test_all_issue_types_are_critical_or_warning() -> None:
    """No info-level issues remain after the redesign."""
    assert set(ISSUE_SEVERITY.values()) <= {"critical", "warning"}
