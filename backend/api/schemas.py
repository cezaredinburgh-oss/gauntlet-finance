"""Pydantic request/response models for the API (not sheet rows)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    app: str
    auth_mode: str
    spreadsheet_configured: bool
    multi_tenant: bool = False


class UploadResponse(BaseModel):
    status: str
    content_sha256: str
    parser_key: str | None = None
    institution: str | None = None
    statement_file_id: str | None = None
    rows_parsed: int = 0
    transactions_written: int = 0
    events_written: int = 0
    lots_written: int = 0
    transfer_pairs_linked: int = 0
    transactions_deduped: int = 0
    events_deduped: int = 0
    message: str = ""
    errors: list[str] = Field(default_factory=list)


class CategoryOverrideRequest(BaseModel):
    transaction_id: UUID


class CategoryOverrideResponse(BaseModel):
    transaction_id: UUID
    category_id: UUID
    category_override: bool = True


class BulkCategoryOverrideRequest(BaseModel):
    category_id: UUID
    transaction_ids: list[UUID] = Field(default_factory=list, min_length=1)


class BulkCategoryOverrideResponse(BaseModel):
    category_id: UUID
    updated: int
    missing: int
    transaction_ids: list[UUID] = Field(default_factory=list)


class ApplyMatchResult(BaseModel):
    scanned: int
    matched: int
    updated: int
    skipped_override: int
    skipped_already: int
    mode: str
    category_id: str
    match_field: str
    match_type: str
    match_value: str


class PriceRefreshResponse(BaseModel):
    as_of: str
    quote_count: int
    total_market_value_usd: str | None
    quotes: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    errors: list[str] = Field(default_factory=list)
    # False when soft refresh found no material mark change (skip client cascade).
    quotes_updated: bool = True


class PriceHistoryPoint(BaseModel):
    date: str
    value: str


class PriceHistoryResponse(BaseModel):
    scope: str
    label: str
    range: str
    currency: str
    series_kind: str
    interval: str = "1d"
    as_of: str
    points: list[PriceHistoryPoint]
    meta: dict[str, Any] = Field(default_factory=dict)


class AuthMeResponse(BaseModel):
    email: str
    name: str | None = None
    picture: str | None = None
    auth_mode: str
    multi_tenant: bool = False
    user_id: str | None = None
    role: str | None = None
    tenant_ready: bool = False
    spreadsheet_bound: bool = False
    is_demo: bool = False
    demo_login_enabled: bool = False


class PasswordLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=200)


class PasswordLoginResponse(BaseModel):
    status: str = "ok"
    email: str
    is_demo: bool = False
    role: str | None = None


class ErrorResponse(BaseModel):
    detail: str
