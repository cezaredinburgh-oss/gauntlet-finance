"""Statement upload + statement-files history/retry endpoints."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from backend.api.deps import RepoDep, SettingsDep, UserDep
from backend.api.schemas import UploadResponse
from backend.services.import_pipeline import ImportPipeline
from backend.services.response_cache import cache_invalidate
from backend.services.statement_files import list_statement_files, retry_statement_file

router = APIRouter(tags=["import"])


def _summary_to_response(summary) -> UploadResponse:
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


def _invalidate(repo) -> None:
    if hasattr(repo, "invalidate_cache"):
        try:
            repo.invalidate_cache()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    cache_invalidate()


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

    _invalidate(repo)
    return _summary_to_response(summary)


@router.get("/statement-files")
async def statement_files_list(
    repo: RepoDep,
    _user: UserDep,
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None, description="Filter by status e.g. ERROR"),
) -> dict[str, Any]:
    return list_statement_files(repo, limit=limit, status=status)


@router.post("/statement-files/{statement_id}/retry", response_model=UploadResponse)
async def statement_files_retry(
    statement_id: UUID,
    repo: RepoDep,
    settings: SettingsDep,
    _user: UserDep,
) -> UploadResponse:
    try:
        summary = retry_statement_file(
            repo,
            statement_id,
            exemption_days=settings.holding_period_exemption_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    _invalidate(repo)
    return _summary_to_response(summary)
