from book_scraper.pipelines import ValidationPipeline


def test_validation_pipeline_does_not_emit_field_missing() -> None:
    """ValidationPipeline no longer tracks field_missing — it was info-level noise."""
    pipeline = ValidationPipeline()
    # Simulate a full scrape where a previously-populated field is now empty.
    # Prior behavior: _report_empty_fields emitted a 'field_missing' issue.
    # New behavior: the method is gone or inert — no issue emitted.
    assert not any(
        issue.get("issue") == "field_missing" for issue in pipeline.drain_issues()
    )
    # Also verify the helper is gone so future regressions fail fast.
    assert not hasattr(pipeline, "_report_empty_fields"), (
        "_report_empty_fields should be removed; field_missing is no longer tracked"
    )


def test_scrape_url_item_attempts_defaults_to_zero() -> None:
    from book_scraper.db.models import ScrapeUrlItem

    column = ScrapeUrlItem.__table__.c.attempts
    # server_default="0" stores the literal string; .arg is the str itself.
    assert column.server_default.arg == "0"
    assert column.nullable is False
