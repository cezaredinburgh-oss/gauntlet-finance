"""Statement upload endpoint."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.api.deps import RepoDep, SettingsDep, UserDep
from backend.api.schemas import UploadResponse
from backend.services.import_pipeline import ImportPipeline
from backend.services.response_cache import cache_invalidate

router = APIRouter(tags=["import"])


@router.post(
    "/upload",
    response_model=UploadResponse,
    summary="Upload a bank/broker statement (CSV or eToro Excel)",
)
async def upload_statement(
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
    file: UploadFile = File(..., description="CSV or eToro .xlsx statement file"),
) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file too large (max 50MB)")

    pipeline = ImportPipeline(
        repo,
        exemption_days=settings.holding_period_exemption_days,
    )
    try:
        summary = pipeline.upload(filename=file.filename, content=content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # New rows must not be hidden behind short-TTL dashboard/alerts caches
    # or a long-lived in-process Sheets tab cache.
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
    )
