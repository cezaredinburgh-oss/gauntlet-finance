"""Statement upload + statement-files history/retry endpoints.

Uploads run as in-process background jobs so reverse proxies (Railway, etc.)
do not kill long crypto/stock imports with plain-text \"upstream error\".
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from backend.api.deps import RepoDep, SettingsDep, UserDep
from backend.api.schemas import (
    UploadAcceptedResponse,
    UploadJobResponse,
    UploadResponse,
)
from backend.common.hashing import sha256_hex
from backend.services.import_pipeline import ImportPipeline
from backend.services.jobs import get_job, start_job
from backend.services.response_cache import cache_invalidate
from backend.services.statement_files import list_statement_files, retry_statement_file
from backend.services.upload_store import load_upload, store_upload
from backend.sheets.repository import SheetsRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["import"])

# Job kind for statement import (single-flight per tenant).
STATEMENT_IMPORT_KIND = "statement-import"


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
        transactions_tagged=getattr(summary, "transactions_tagged", 0),
        transactions_internal_flagged=getattr(summary, "transactions_internal_flagged", 0),
        transactions_categorized=getattr(summary, "transactions_categorized", 0),
        message=summary.message,
        errors=summary.errors,
        ai_map_eligible=bool(getattr(summary, "ai_map_eligible", False)),
    )


def _summary_to_dict(summary) -> dict[str, Any]:
    return _summary_to_response(summary).model_dump(mode="json")


def _invalidate(repo: SheetsRepository) -> None:
    if hasattr(repo, "invalidate_cache"):
        try:
            repo.invalidate_cache()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    cache_invalidate()


def _run_statement_import(repo: SheetsRepository, params: dict[str, Any]) -> dict[str, Any]:
    """Background worker: load stored bytes and run ImportPipeline."""
    filename = str(params.get("filename") or "upload.csv")
    content_sha = str(params.get("content_sha256") or "").lower()
    exemption_days = int(params.get("exemption_days") or 1095)
    content = load_upload(content_sha)
    if content is None:
        raise ValueError(
            "Upload payload expired or missing from store — re-select the file and try again."
        )
    pipeline = ImportPipeline(repo, exemption_days=exemption_days)
    summary = pipeline.upload(filename=filename, content=content)
    _invalidate(repo)
    return _summary_to_dict(summary)


@router.post(
    "/upload",
    response_model=UploadAcceptedResponse,
    summary="Upload a bank/broker statement (async import)",
)
async def upload_statement(
    repo: RepoDep,
    settings: SettingsDep,
    user: UserDep,
    file: UploadFile = File(..., description="CSV or eToro .xlsx statement file"),
) -> UploadAcceptedResponse:
    """
    Accept file bytes immediately and import in a background job.

    Client should poll ``GET /upload/jobs/{job_id}`` until status is done/error.
    This avoids proxy idle timeouts on long crypto/stock FIFO+Sheets writes.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file too large (max 50MB)")

    content_sha = sha256_hex(content)
    # Persist for worker + ERROR retry
    await asyncio.to_thread(store_upload, content_sha, content)

    tenant = user.user_id if settings.multi_tenant else None
    # Unique kind per content hash so multi-file sequential batches are not blocked
    # by a single global lock — still one job per file content.
    kind = f"{STATEMENT_IMPORT_KIND}:{content_sha[:16]}"
    out = start_job(
        kind,
        repo,
        params={
            "filename": file.filename,
            "content_sha256": content_sha,
            "exemption_days": settings.holding_period_exemption_days,
        },
        runner=_run_statement_import,
        tenant_id=tenant,
    )
    if out.get("status") == "rejected":
        # Same file already importing
        raise HTTPException(
            status_code=409,
            detail=out.get("error") or "Import already running for this file",
        )
    job_id = str(out.get("job_id") or "")
    if not job_id:
        raise HTTPException(status_code=500, detail="Failed to start import job")

    return UploadAcceptedResponse(
        job_id=job_id,
        status="running",
        filename=file.filename,
        content_sha256=content_sha,
        message=(
            "Import started in the background. "
            "Large crypto/stock ledgers can take several minutes on Google Sheets."
        ),
    )


@router.get(
    "/upload/jobs/{job_id}",
    response_model=UploadJobResponse,
    summary="Poll background statement import status",
)
async def upload_job_status(
    job_id: str,
    user: UserDep,
    settings: SettingsDep,
) -> UploadJobResponse:
    tenant = user.user_id if settings.multi_tenant else None
    job = get_job(job_id, tenant_id=tenant)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    kind = str(job.get("kind") or "")
    if not kind.startswith(STATEMENT_IMPORT_KIND):
        raise HTTPException(status_code=404, detail="Import job not found")

    params = job.get("params") or {}
    result_raw = job.get("result")
    result: UploadResponse | None = None
    if isinstance(result_raw, dict) and job.get("status") == "done":
        try:
            result = UploadResponse.model_validate(result_raw)
        except Exception:  # noqa: BLE001
            logger.warning("upload job %s result failed validation", job_id)
            result = None

    return UploadJobResponse(
        job_id=str(job.get("id") or job_id),
        status=str(job.get("status") or "unknown"),
        kind=kind,
        filename=str(params.get("filename") or "") or None,
        content_sha256=str(params.get("content_sha256") or "") or None,
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
        error=job.get("error"),
        result=result,
    )


@router.get("/statement-files")
async def statement_files_list(
    repo: RepoDep,
    _user: UserDep,
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None, description="Filter by status e.g. ERROR"),
) -> dict[str, Any]:
    return list_statement_files(repo, limit=limit, status=status)


@router.post("/statement-files/{statement_id}/retry", response_model=UploadAcceptedResponse)
async def statement_files_retry(
    statement_id: UUID,
    repo: RepoDep,
    settings: SettingsDep,
    user: UserDep,
) -> UploadAcceptedResponse:
    """
    Retry a failed/pending statement file in the background.
    """
    from backend.schema.models import StatementFile, StatementFileStatus

    row = repo.get_by_id("StatementFiles", statement_id)
    if row is None or not isinstance(row, StatementFile) or row.archived:
        raise HTTPException(status_code=404, detail="Statement file not found")
    if row.status not in (
        StatementFileStatus.ERROR,
        StatementFileStatus.PENDING,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Only ERROR/PENDING statements can be retried (got {row.status.value})",
        )
    sha = (row.content_sha256 or "").lower()
    if not sha:
        raise HTTPException(status_code=400, detail="Statement has no content hash")
    content = load_upload(sha)
    if content is None:
        raise HTTPException(
            status_code=400,
            detail="Original file bytes not on server — re-upload the file",
        )

    tenant = user.user_id if settings.multi_tenant else None
    kind = f"{STATEMENT_IMPORT_KIND}:retry:{statement_id}"
    filename = row.original_filename or "retry.csv"

    def _retry_runner(r: SheetsRepository, params: dict[str, Any]) -> dict[str, Any]:
        summary = retry_statement_file(
            r,
            UUID(str(params["statement_id"])),
            exemption_days=int(params.get("exemption_days") or 1095),
        )
        _invalidate(r)
        return _summary_to_dict(summary)

    out = start_job(
        kind,
        repo,
        params={
            "statement_id": str(statement_id),
            "filename": filename,
            "content_sha256": sha,
            "exemption_days": settings.holding_period_exemption_days,
        },
        runner=_retry_runner,
        tenant_id=tenant,
    )
    if out.get("status") == "rejected":
        raise HTTPException(
            status_code=409,
            detail=out.get("error") or "Retry already running",
        )
    job_id = str(out.get("job_id") or "")
    if not job_id:
        raise HTTPException(status_code=500, detail="Failed to start retry job")
    return UploadAcceptedResponse(
        job_id=job_id,
        status="running",
        filename=filename,
        content_sha256=sha,
        message="Retry started in the background.",
    )
