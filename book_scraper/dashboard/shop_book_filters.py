from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, TypedDict

from sqlalchemy import and_, false, func, or_

from book_scraper.db.models import ShopBook

FilterKind = Literal["text", "int", "decimal", "bool", "date", "array"]


class ShopBookFieldFilter(TypedDict, total=False):
    operator: str
    value: str


@dataclass(frozen=True)
class ShopBookFieldSpec:
    name: str
    label: str
    kind: FilterKind
    placeholder: str = ""


TEXT_OPERATORS = (
    ("any", "Any"),
    ("empty", "Empty / null"),
    ("has_value", "Has value"),
    ("contains", "Contains"),
)
NUMBER_OPERATORS = (
    ("any", "Any"),
    ("empty", "Null"),
    ("has_value", "Has value"),
    ("equals", "Equals"),
)
DATE_OPERATORS = (
    ("any", "Any"),
    ("empty", "Null"),
    ("has_value", "Has value"),
    ("on", "On date"),
)
BOOL_OPERATORS = (
    ("any", "Any"),
    ("true", "True"),
    ("false", "False"),
)
ARRAY_OPERATORS = (
    ("any", "Any"),
    ("empty", "Empty / null"),
    ("has_value", "Has value"),
    ("contains", "Contains item"),
)
GENERIC_FIELD_OPERATORS = (
    ("any", "Any"),
    ("empty", "Empty / null"),
    ("has_value", "Has value"),
    ("contains", "Contains"),
    ("equals", "Equals"),
    ("true", "True"),
    ("false", "False"),
    ("on", "On date"),
)

SHOP_BOOK_FIELD_SPECS = (
    ShopBookFieldSpec("id", "ID", "int", "e.g. 123"),
    ShopBookFieldSpec("url", "URL", "text", "e.g. vaga.lt"),
    ShopBookFieldSpec("title", "Title", "text", "e.g. Altoriu sesely"),
    ShopBookFieldSpec("author", "Author", "text", "e.g. Salomeja Neris"),
    ShopBookFieldSpec("sku", "SKU", "text"),
    ShopBookFieldSpec("isbn", "ISBN", "text"),
    ShopBookFieldSpec("publisher", "Publisher", "text"),
    ShopBookFieldSpec("year", "Year", "int", "e.g. 2024"),
    ShopBookFieldSpec("format", "Format", "text", "e.g. Hardcover"),
    ShopBookFieldSpec("type", "Type", "text", "e.g. book"),
    ShopBookFieldSpec("description", "Description", "text"),
    ShopBookFieldSpec("image_url", "Image URL", "text"),
    ShopBookFieldSpec("categories", "Categories", "array", "Exact category name"),
    ShopBookFieldSpec("price", "Price", "decimal", "e.g. 12.99"),
    ShopBookFieldSpec("price_original", "Original Price", "decimal", "e.g. 19.99"),
    ShopBookFieldSpec("in_stock", "In Stock", "bool"),
    ShopBookFieldSpec("match_status", "Match Status", "text"),
    ShopBookFieldSpec("match_method", "Match Method", "text"),
    ShopBookFieldSpec("last_run_id", "Last Run ID", "int"),
    ShopBookFieldSpec("last_run_action", "Last Run Action", "text"),
    ShopBookFieldSpec("inactive_since", "Inactive Since", "date"),
    ShopBookFieldSpec("first_seen_at", "First Seen", "date"),
    ShopBookFieldSpec("last_seen_at", "Last Seen", "date"),
)

FIELD_SPEC_BY_NAME = {spec.name: spec for spec in SHOP_BOOK_FIELD_SPECS}


def _operator_choices(kind: FilterKind) -> tuple[tuple[str, str], ...]:
    return {
        "text": TEXT_OPERATORS,
        "int": NUMBER_OPERATORS,
        "decimal": NUMBER_OPERATORS,
        "bool": BOOL_OPERATORS,
        "date": DATE_OPERATORS,
        "array": ARRAY_OPERATORS,
    }[kind]


def _trimmed(value: str | None) -> str:
    return (value or "").strip()


def parse_shop_book_field_filters(query_params: Any) -> dict[str, ShopBookFieldFilter]:
    filters: dict[str, ShopBookFieldFilter] = {}
    for spec in SHOP_BOOK_FIELD_SPECS:
        operator = _trimmed(query_params.get(f"field_{spec.name}_op")) or "any"
        value = _trimmed(query_params.get(f"field_{spec.name}_value"))
        allowed = {code for code, _label in _operator_choices(spec.kind)}
        if operator not in allowed or operator == "any":
            continue
        if spec.kind == "bool":
            filters[spec.name] = {"operator": operator}
            continue
        if operator in {"empty", "has_value"}:
            filters[spec.name] = {"operator": operator}
            continue
        if value:
            filters[spec.name] = {"operator": operator, "value": value}

    generic_field_name = _trimmed(query_params.get("field_name"))
    generic_operator = _trimmed(query_params.get("field_op")) or "any"
    generic_value = _trimmed(query_params.get("field_value"))
    generic_spec = FIELD_SPEC_BY_NAME.get(generic_field_name)
    if generic_spec is not None:
        allowed = {code for code, _label in _operator_choices(generic_spec.kind)}
        if generic_operator in allowed and generic_operator != "any":
            if generic_spec.kind == "bool" or generic_operator in {
                "empty",
                "has_value",
            }:
                filters[generic_field_name] = {"operator": generic_operator}
            elif generic_value:
                filters[generic_field_name] = {
                    "operator": generic_operator,
                    "value": generic_value,
                }
    return filters


def get_shop_book_field_options() -> list[dict[str, str]]:
    return [{"value": spec.name, "label": spec.label} for spec in SHOP_BOOK_FIELD_SPECS]


def get_shop_book_field_filter_states(query_params: Any) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    active = parse_shop_book_field_filters(query_params)
    for spec in SHOP_BOOK_FIELD_SPECS:
        current = active.get(spec.name, {})
        states.append(
            {
                "name": spec.name,
                "label": spec.label,
                "kind": spec.kind,
                "operator": current.get("operator", "any"),
                "value": current.get(
                    "value", _trimmed(query_params.get(f"field_{spec.name}_value"))
                ),
                "operators": [
                    {"value": value, "label": label}
                    for value, label in _operator_choices(spec.kind)
                ],
                "show_value_input": spec.kind != "bool",
                "input_type": {
                    "text": "text",
                    "int": "number",
                    "decimal": "number",
                    "date": "date",
                    "array": "text",
                    "bool": "text",
                }[spec.kind],
                "input_step": {"int": "1", "decimal": "0.01"}.get(spec.kind, ""),
                "placeholder": spec.placeholder,
            }
        )
    return states


def get_shop_book_field_filter_params(
    field_filters: dict[str, ShopBookFieldFilter],
) -> dict[str, str]:
    params: dict[str, str] = {}
    for field_name, field_filter in field_filters.items():
        params[f"field_{field_name}_op"] = field_filter["operator"]
        value = field_filter.get("value")
        if value:
            params[f"field_{field_name}_value"] = value
    return params


def describe_shop_book_field_filter(
    field_name: str, field_filter: ShopBookFieldFilter
) -> str:
    spec = FIELD_SPEC_BY_NAME[field_name]
    operator = field_filter["operator"]
    value = field_filter.get("value")
    if operator == "empty":
        return f"{spec.label}: empty / null"
    if operator == "has_value":
        return f"{spec.label}: has value"
    if operator == "contains" and value:
        return f'{spec.label}: contains "{value}"'
    if operator == "equals" and value:
        return f"{spec.label}: {value}"
    if operator == "on" and value:
        return f"{spec.label}: {value}"
    if operator in {"true", "false"}:
        return f"{spec.label}: {operator}"
    return spec.label


def _text_is_empty(column: Any) -> Any:
    return or_(column.is_(None), func.btrim(column) == "")


def _text_has_value(column: Any) -> Any:
    return and_(column.isnot(None), func.btrim(column) != "")


def _array_is_empty(column: Any) -> Any:
    return or_(column.is_(None), func.cardinality(column) == 0)


def _array_has_value(column: Any) -> Any:
    return and_(column.isnot(None), func.cardinality(column) > 0)


def apply_shop_book_field_filters(
    query: Any, field_filters: dict[str, ShopBookFieldFilter]
) -> Any:
    for field_name, field_filter in field_filters.items():
        spec = FIELD_SPEC_BY_NAME.get(field_name)
        if spec is None:
            continue
        column = getattr(ShopBook, field_name)
        operator = field_filter["operator"]
        value = field_filter.get("value")

        if spec.kind == "text":
            if operator == "empty":
                query = query.filter(_text_is_empty(column))
            elif operator == "has_value":
                query = query.filter(_text_has_value(column))
            elif operator == "contains" and value:
                query = query.filter(column.ilike(f"%{value}%"))
        elif spec.kind == "array":
            if operator == "empty":
                query = query.filter(_array_is_empty(column))
            elif operator == "has_value":
                query = query.filter(_array_has_value(column))
            elif operator == "contains" and value:
                query = query.filter(column.any(value))
        elif spec.kind == "int":
            if operator == "empty":
                query = query.filter(column.is_(None))
            elif operator == "has_value":
                query = query.filter(column.isnot(None))
            elif operator == "equals" and value:
                try:
                    query = query.filter(column == int(value))
                except ValueError:
                    query = query.filter(false())
        elif spec.kind == "decimal":
            if operator == "empty":
                query = query.filter(column.is_(None))
            elif operator == "has_value":
                query = query.filter(column.isnot(None))
            elif operator == "equals" and value:
                try:
                    query = query.filter(column == Decimal(value))
                except InvalidOperation:
                    query = query.filter(false())
        elif spec.kind == "bool":
            if operator == "true":
                query = query.filter(column.is_(True))
            elif operator == "false":
                query = query.filter(column.is_(False))
        elif spec.kind == "date":
            if operator == "empty":
                query = query.filter(column.is_(None))
            elif operator == "has_value":
                query = query.filter(column.isnot(None))
            elif operator == "on" and value:
                try:
                    query = query.filter(func.date(column) == date.fromisoformat(value))
                except ValueError:
                    query = query.filter(false())
    return query
