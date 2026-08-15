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
    transactions_tagged: int = 0
    transactions_internal_flagged: int = 0
    transactions_categorized: int = 0
    message: str = ""
    errors: list[str] = Field(default_factory=list)
    ai_map_eligible: bool = False


class UploadAcceptedResponse(BaseModel):
    """Immediate response after accepting a statement for background import."""

    job_id: str
    status: str = "running"
    filename: str = ""
    content_sha256: str = ""
    message: str = "Import started in the background. Poll job status until done."


class UploadJobResponse(BaseModel):
    """Polled status for a background statement import."""

    job_id: str
    status: str  # running | done | error
    kind: str = "statement-import"
    filename: str | None = None
    content_sha256: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    result: UploadResponse | None = None


class CategoryOverrideRequest(BaseModel):
    transaction_id: UUID


class CategoryOverrideResponse(BaseModel):
    transaction_id: UUID
    category_id: UUID
    category_override: bool = True


class BulkCategoryOverrideRequest(BaseModel):
    category_id: UUID
    transaction_ids: list[UUID] = Field(default_factory=list, min_length=1)
    is_internal_transfer: bool | None = None


class BulkCategoryOverrideResponse(BaseModel):
    category_id: UUID
    updated: int
    missing: int
    transaction_ids: list[UUID] = Field(default_factory=list)


class RestoreAssignmentItem(BaseModel):
    """Previous category state for undo (category_id null = clear)."""

    transaction_id: UUID
    category_id: UUID | None = None
    category_override: bool = False
    is_internal_transfer: bool | None = None


class RestoreAssignmentsRequest(BaseModel):
    items: list[RestoreAssignmentItem] = Field(default_factory=list, min_length=1)


class RestoreAssignmentsResponse(BaseModel):
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
    demo_kind: str | None = None  # "sandbox" | "tour" | "lab" | null
    read_only: bool = False


class PasswordLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=200)


class PasswordLoginResponse(BaseModel):
    status: str = "ok"
    email: str
    is_demo: bool = False
    role: str | None = None
    demo_kind: str | None = None
    read_only: bool = False


class ErrorResponse(BaseModel):
    detail: str
