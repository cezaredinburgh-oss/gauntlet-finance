"""Encode/decode Pydantic sheet rows ↔ Google Sheets cell grids."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from types import UnionType
from typing import Any, Union, get_args, get_origin
from uuid import UUID

from backend.schema.models import TAB_MODEL, SheetRow


def _unwrap_optional(annotation: Any) -> tuple[bool, Any]:
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return True, args[0]
    return False, annotation


def encode_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        # Avoid scientific notation; trim trailing zeros carefully
        s = format(value, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def decode_cell(annotation: Any, raw: str) -> Any:
    is_opt, inner = _unwrap_optional(annotation)
    text = (raw if raw is not None else "").strip()
    if text == "":
        return None if is_opt else ("" if inner is str else None)

    ann = inner
    if ann is bool:
        return text.upper() in {"TRUE", "1", "YES", "Y"}
    if ann is UUID:
        return UUID(text)
    if ann is Decimal:
        return Decimal(text)
    if ann is int:
        return int(float(text))
    if ann is date:
        return date.fromisoformat(text[:10])
    if ann is datetime:
        t = text
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        return datetime.fromisoformat(t)
    if isinstance(ann, type) and issubclass(ann, Enum):
        return ann(text)
    if ann is str:
        return text
    return text


def model_to_row(model: SheetRow, headers: list[str]) -> list[str]:
    data = model.model_dump(mode="python")
    return [encode_cell(data.get(h)) for h in headers]


def row_to_model(tab: str, headers: list[str], values: list[str]) -> SheetRow:
    model_cls = TAB_MODEL[tab]
    payload: dict[str, Any] = {}
    fields = model_cls.model_fields
    for h, v in zip(headers, values + [""] * max(0, len(headers) - len(values))):
        if h not in fields:
            continue
        payload[h] = decode_cell(fields[h].annotation, v)
    return model_cls.model_validate(payload)


def models_to_grid(tab: str, rows: list[SheetRow], headers: list[str]) -> list[list[str]]:
    grid = [headers]
    for row in rows:
        if not isinstance(row, TAB_MODEL[tab]):
            raise TypeError(f"row type mismatch for {tab}")
        grid.append(model_to_row(row, headers))
    return grid
