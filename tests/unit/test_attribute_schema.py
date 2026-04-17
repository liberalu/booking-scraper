from types import SimpleNamespace

from book_scraper.config_models import AttributeRule, AttributesConfig
from book_scraper.items import ListingItem
from book_scraper.pipelines import ValidationPipeline


def _pipeline_with_schema(schema: AttributesConfig | None) -> ValidationPipeline:
    pipeline = ValidationPipeline()
    spider = SimpleNamespace(conf=SimpleNamespace(attributes=schema))
    pipeline.crawler = SimpleNamespace(spider=spider)  # type: ignore[assignment]
    return pipeline


def _item(**properties: str) -> ListingItem:
    return ListingItem(
        url="https://vaga.lt/x",
        shop_name="vaga",
        title="Title",
        price="9.99",
        properties=dict(properties),
    )


def test_no_schema_means_no_attribute_issues() -> None:
    p = _pipeline_with_schema(None)
    p.process_item(_item(format="hardcover", lenguage="lt"))
    assert [i["issue"] for i in p.issues if i["field"] == "properties"] == []


def test_unknown_key_fires_attribute_unknown_key() -> None:
    schema = AttributesConfig(allowed_keys=["format", "language"])
    p = _pipeline_with_schema(schema)
    p.process_item(_item(format="hardcover", lenguage="lt"))
    issues = [i for i in p.issues if i["issue"] == "attribute_unknown_key"]
    assert len(issues) == 1
    assert "lenguage" in str(issues[0]["raw_value"])


def test_enum_violation_fires_attribute_invalid_value() -> None:
    schema = AttributesConfig(
        allowed_keys=["format"],
        rules={"format": AttributeRule(enum=["hardcover", "paperback"])},
    )
    p = _pipeline_with_schema(schema)
    p.process_item(_item(format="audiobook"))
    issues = [i for i in p.issues if i["issue"] == "attribute_invalid_value"]
    assert len(issues) == 1
    assert issues[0]["field"] == "format"


def test_pattern_violation_fires_attribute_invalid_value() -> None:
    schema = AttributesConfig(
        allowed_keys=["page_count"],
        rules={"page_count": AttributeRule(pattern=r"^\d+$")},
    )
    p = _pipeline_with_schema(schema)
    p.process_item(_item(page_count="two hundred"))
    issues = [i for i in p.issues if i["issue"] == "attribute_invalid_value"]
    assert len(issues) == 1


def test_valid_attributes_pass() -> None:
    schema = AttributesConfig(
        allowed_keys=["format", "page_count"],
        rules={
            "format": AttributeRule(enum=["hardcover"]),
            "page_count": AttributeRule(pattern=r"^\d+$"),
        },
    )
    p = _pipeline_with_schema(schema)
    p.process_item(_item(format="hardcover", page_count="250"))
    attr_issues = [
        i
        for i in p.issues
        if i["issue"] in {"attribute_unknown_key", "attribute_invalid_value"}
    ]
    assert attr_issues == []


def test_attributes_config_from_toml_splits_subtables() -> None:
    raw = {
        "allowed_keys": ["format", "language"],
        "format": {"enum": ["hardcover", "paperback"]},
        "language": {"pattern": r"^[a-z]{2}$"},
    }
    cfg = AttributesConfig.from_toml(raw)  # type: ignore[arg-type]
    assert cfg.allowed_keys == ["format", "language"]
    assert cfg.rules["format"].enum == ["hardcover", "paperback"]
    assert cfg.rules["language"].pattern == r"^[a-z]{2}$"
