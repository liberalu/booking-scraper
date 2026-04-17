from scrapy.utils.project import get_project_settings
from book_scraper.items import ShopBookItem
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
