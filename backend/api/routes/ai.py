"""Grok / SpaceXAI assist endpoints (suggest-only categorize + cash map)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.api.deps import RepoDep, SettingsDep, UserDep, WritableUserDep
from backend.api.schemas import UploadResponse
from backend.common.hashing import sha256_hex
from backend.services import ai_categorize, ai_quota, ai_statement_map
from backend.services.import_pipeline import ImportPipeline
from backend.services.response_cache import cache_invalidate
from backend.services.upload_store import load_upload, store_upload

router = APIRouter(prefix="/ai", tags=["ai"])


class AiStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    model: str | None = None
    daily_token_cap: int = 0
    max_merchants_per_request: int = 0
    byok: bool = False
    mode: str = "off"
    sandbox_fallback: bool = False
    quota_used: int = 0
    quota_cap: int = 0
    quota_remaining: int = 0


class CategorizeSuggestRequest(BaseModel):
    """Optional scope; empty = all blank merchants in the ledger (capped)."""

    source_file_ids: list[str] = Field(default_factory=list)
    limit: int | None = None
    exclude_merchant_keys: list[str] = Field(default_factory=list)
    merchant_key: str | None = None
    hint: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class CategorySuggestionItem(BaseModel):
    merchant_key: str
    label: str
    category_id: str
    category_name: str
    confidence: float
    reason: str
    transaction_ids: list[str]
    sample_count: int
    needs_human: bool = False


class CategorizeSuggestResponse(BaseModel):
    enabled: bool
    configured: bool
    model: str | None = None
    suggestions: list[CategorySuggestionItem]
    merchants_considered: int
    merchants_suggested: int
    tokens_used: int
    quota_used: int
    quota_cap: int
    message: str | None = None


def _is_writable_sandbox(user) -> bool:
    """Writable demo principals that may use offline AI heuristics when no XAI key."""
    kind = getattr(user, "demo_kind", "") or ""
    return bool(user.is_demo and kind in {"sandbox", "lab"})


@router.get("/status", response_model=AiStatusResponse)
def ai_status(user: UserDep, settings: SettingsDep) -> AiStatusResponse:
    base = ai_categorize.status_payload(
        settings, sandbox=_is_writable_sandbox(user)
    )
    principal = ai_quota.principal_key(user.user_id, user.email)
    snap = ai_quota.snapshot(
        principal,
        cap=settings.ai_daily_token_cap,
        global_cap=settings.ai_global_daily_token_cap,
    )
    return AiStatusResponse(
        **base,
        quota_used=snap.used,
        quota_cap=snap.cap,
        quota_remaining=snap.remaining,
    )


@router.post("/categorize-suggest", response_model=CategorizeSuggestResponse)
def categorize_suggest(
    body: CategorizeSuggestRequest,
    user: WritableUserDep,
    repo: RepoDep,
    settings: SettingsDep,
) -> CategorizeSuggestResponse:
    """
    Suggest categories for uncategorized merchants (human apply separately).

    Does not write to the ledger. Payload sent to Grok is minimized (labels only).
    """
    principal = ai_quota.principal_key(user.user_id, user.email)
    result = ai_categorize.suggest_categories(
        repo,
        principal=principal,
        settings=settings,
        source_file_ids=body.source_file_ids or None,
        limit=body.limit,
        exclude_merchant_keys=body.exclude_merchant_keys or None,
        merchant_key=body.merchant_key,
        hint=body.hint,
        date_from=body.date_from,
        date_to=body.date_to,
        sandbox=_is_writable_sandbox(user),
    )
    return CategorizeSuggestResponse(
        enabled=result.enabled,
        configured=result.configured,
        model=result.model,
        suggestions=[
            CategorySuggestionItem(
                merchant_key=s.merchant_key,
                label=s.label,
                category_id=s.category_id,
                category_name=s.category_name,
                confidence=s.confidence,
                reason=s.reason,
                transaction_ids=s.transaction_ids,
                sample_count=s.sample_count,
                needs_human=bool(s.needs_human),
            )
            for s in result.suggestions
        ],
        merchants_considered=result.merchants_considered,
        merchants_suggested=result.merchants_suggested,
        tokens_used=result.tokens_used,
        quota_used=result.quota_used,
        quota_cap=result.quota_cap,
        message=result.message,
    )


class ColumnMapBody(BaseModel):
    institution: str = "Other"
    default_currency: str | None = None
    amount_sign: str = "as_is"
    columns: dict[str, str] = Field(default_factory=dict)
    confidence: float = 1.0
    notes: str = ""


class MapPreviewRow(BaseModel):
    booking_date: str
    amount: str
    currency: str
    merchant: str
    description: str


class MapStatementResponse(BaseModel):
    enabled: bool
    configured: bool
    model: str | None = None
    content_sha256: str
    eligible: bool
    headers: list[str]
    delimiter: str
    sample_row_count: int
    total_data_rows: int
    mapping: ColumnMapBody | None = None
    preview: list[MapPreviewRow]
    tokens_used: int
    quota_used: int
    quota_cap: int
    message: str | None = None


class ImportMappedRequest(BaseModel):
    content_sha256: str
    filename: str = "statement.csv"
    mapping: ColumnMapBody
    headers: list[str] = Field(default_factory=list)


def _map_result_to_response(result: ai_statement_map.MapResult) -> MapStatementResponse:
    mapping = None
    if result.mapping is not None:
        m = result.mapping
        mapping = ColumnMapBody(
            institution=m.institution,
            default_currency=m.default_currency,
            amount_sign=m.amount_sign,
            columns=dict(m.columns),
            confidence=m.confidence,
            notes=m.notes,
        )
    return MapStatementResponse(
        enabled=result.enabled,
        configured=result.configured,
        model=result.model,
        content_sha256=result.content_sha256,
        eligible=result.eligible,
        headers=result.headers,
        delimiter=result.delimiter,
        sample_row_count=result.sample_row_count,
        total_data_rows=result.total_data_rows,
        mapping=mapping,
        preview=[
            MapPreviewRow(
                booking_date=p.booking_date,
                amount=p.amount,
                currency=p.currency,
                merchant=p.merchant,
                description=p.description,
            )
            for p in result.preview
        ],
        tokens_used=result.tokens_used,
        quota_used=result.quota_used,
        quota_cap=result.quota_cap,
        message=result.message,
    )


@router.post("/map-statement", response_model=MapStatementResponse)
async def map_statement(
    user: WritableUserDep,
    settings: SettingsDep,
    content_sha256: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
) -> MapStatementResponse:
    """
    Propose a cash CSV column map via Grok (preview only — no ledger write).

    Provide either stored ``content_sha256`` from a failed upload, or a file.
    """
    content: bytes | None = None
    if file is not None and file.filename:
        raw = await file.read()
        if raw:
            content = raw
            store_upload(sha256_hex(content), content)
    if not content and content_sha256:
        content = load_upload(content_sha256.strip().lower())
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Provide a CSV file or a content_sha256 from a prior upload on this server.",
        )
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file too large (max 50MB)")

    principal = ai_quota.principal_key(user.user_id, user.email)
    result = await asyncio.to_thread(
        ai_statement_map.map_statement_bytes,
        content,
        principal=principal,
        settings=settings,
        sandbox=_is_writable_sandbox(user),
    )
    return _map_result_to_response(result)


@router.post("/import-mapped", response_model=UploadResponse)
async def import_mapped(
    body: ImportMappedRequest,
    user: WritableUserDep,
    repo: RepoDep,
    settings: SettingsDep,
) -> UploadResponse:
    """Confirm an AI cash column map and run the normal import pipeline."""
    sha = (body.content_sha256 or "").strip().lower()
    content = load_upload(sha) if sha else None
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Statement bytes not found for this content_sha256. Re-upload the file.",
        )
    try:
        mapping = ai_statement_map.column_map_from_dict(
            body.mapping.model_dump(),
            headers=body.headers or list(body.mapping.columns.keys()),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pipeline = ImportPipeline(
        repo,
        exemption_days=settings.holding_period_exemption_days,
    )
    try:
        summary = await asyncio.to_thread(
            pipeline.import_ai_mapped_cash,
            filename=body.filename or "statement.csv",
            content=content,
            mapping=mapping,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if hasattr(repo, "invalidate_cache"):
        try:
            repo.invalidate_cache()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    cache_invalidate()

    return UploadResponse(
        status=summary.status,
        content_sha256=summary.content_sha256,
        parser_key=summary.parser_key,
        institution=summary.institution,
        statement_file_id=summary.statement_file_id,
        rows_parsed=summary.rows_parsed,
        transactions_written=summary.transactions_written,
        events_written=summary.events_written,
        lots_written=summary.lots_written,
        transfer_pairs_linked=summary.transfer_pairs_linked,
        transactions_deduped=summary.transactions_deduped,
        events_deduped=summary.events_deduped,
        message=summary.message,
        errors=summary.errors,
        ai_map_eligible=bool(getattr(summary, "ai_map_eligible", False)),
    )
