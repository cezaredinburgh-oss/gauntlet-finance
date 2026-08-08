"""StatementFiles listing and retry helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from backend.common.timeutil import utc_now
from backend.schema.models import StatementFile, StatementFileStatus
from backend.services.import_pipeline import ImportPipeline, UploadSummary
from backend.services.upload_store import has_upload, load_upload
from backend.sheets.repository import SheetsRepository


def list_statement_files(
    repo: SheetsRepository,
    *,
    limit: int = 50,
    status: str | None = None,
) -> dict[str, Any]:
    rows = [
        r
        for r in repo.list_rows("StatementFiles")
        if isinstance(r, StatementFile) and not r.archived
    ]
    if status:
        want = status.strip().lower().replace("_", "")
        rows = [
            r
            for r in rows
            if r.status.value.lower().replace("_", "") == want
            or r.status.name.lower() == status.strip().lower()
        ]
    rows.sort(key=lambda r: r.uploaded_at or r.created_at, reverse=True)
    rows = rows[: max(1, min(limit, 200))]
    items = []
    for r in rows:
        items.append(
            {
                "id": str(r.id),
                "original_filename": r.original_filename,
                "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
                "content_sha256": r.content_sha256,
                "institution": r.institution,
                "row_count": r.row_count,
                "parser_key": r.parser_key,
                "status": r.status.value,
                "notes": r.notes,
                "has_stored_bytes": has_upload(r.content_sha256),
                "retryable": r.status
                in (StatementFileStatus.ERROR, StatementFileStatus.PENDING)
                and has_upload(r.content_sha256),
            }
        )
    return {"total": len(items), "items": items}


def retry_statement_file(
    repo: SheetsRepository,
    statement_id: UUID,
    *,
    exemption_days: int = 1095,
) -> UploadSummary:
    row = repo.get_by_id("StatementFiles", statement_id)
    if row is None or not isinstance(row, StatementFile) or row.archived:
        raise ValueError("statement file not found")
    if row.status not in (
        StatementFileStatus.ERROR,
        StatementFileStatus.PENDING,
    ):
        raise ValueError(
            f"only ERROR/PENDING can retry (status={row.status.value})"
        )
    blob = load_upload(row.content_sha256)
    if blob is None:
        raise ValueError(
            "original file bytes not stored — re-upload the file manually"
        )

    pipe = ImportPipeline(repo, exemption_days=exemption_days)
    # Register path resets ERROR → PENDING and re-runs (row dedupe on partials)
    return pipe.upload(
        filename=row.original_filename or "retry.bin",
        content=blob,
    )
