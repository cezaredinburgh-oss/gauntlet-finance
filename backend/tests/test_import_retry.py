"""Failed imports must not permanently gate re-upload of the same SHA-256."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from backend.engines.statements import StatementService
from backend.schema.models import StatementFileStatus
from backend.services.import_pipeline import ImportPipeline
from backend.sheets.repository import InMemorySheetsRepository
from backend.scripts.seed_dev_repo import seed_minimal

FIXTURES = Path(__file__).parent / "fixtures"


def test_error_and_pending_do_not_block_is_duplicate():
    repo = InMemorySheetsRepository()
    svc = StatementService(repo)
    data = b"same-bytes"

    reg = svc.register_statement(
        filename="a.csv",
        file_bytes=data,
        institution="Revolut",
        row_count=0,
        parser_key=None,
        status=StatementFileStatus.PENDING,
    )
    assert reg.status == "new"
    assert svc.is_duplicate(reg.content_sha256) is False

    svc.mark_status(reg.statement.id, StatementFileStatus.ERROR, notes="quota")
    assert svc.is_duplicate(reg.content_sha256) is False

    svc.mark_imported(reg.statement.id, row_count=1)
    assert svc.is_duplicate(reg.content_sha256) is True


def test_register_retries_pending_and_error_rows():
    repo = InMemorySheetsRepository()
    svc = StatementService(repo)
    data = b"retry-me"

    first = svc.register_statement(
        filename="a.csv",
        file_bytes=data,
        institution="Unknown",
        row_count=0,
        parser_key=None,
    )
    assert first.status == "new"

    # Still PENDING — must allow re-register (not "duplicate")
    second = svc.register_statement(
        filename="a.csv",
        file_bytes=data,
        institution="Unknown",
        row_count=0,
        parser_key=None,
    )
    assert second.status == "new"
    assert second.statement.id == first.statement.id
    assert len(repo.list_rows("StatementFiles")) == 1

    svc.mark_status(first.statement.id, StatementFileStatus.ERROR, notes="fail")
    third = svc.register_statement(
        filename="a.csv",
        file_bytes=data,
        institution="Unknown",
        row_count=0,
        parser_key=None,
    )
    assert third.status == "new"
    assert third.statement.status == StatementFileStatus.PENDING

    svc.mark_imported(third.statement.id)
    fourth = svc.register_statement(
        filename="a.csv",
        file_bytes=data,
        institution="Unknown",
        row_count=0,
        parser_key=None,
    )
    assert fourth.status == "duplicate"


def test_pipeline_marks_error_on_persist_failure_then_allows_retry(monkeypatch):
    """Simulate Sheets 429 mid-write: status=error, re-upload not already_imported."""
    repo = InMemorySheetsRepository()
    seed_minimal(repo)
    path = FIXTURES / "raiffeisen_sample.csv"
    data = path.read_bytes()
    pipeline = ImportPipeline(repo)

    original_upsert = repo.upsert_rows
    calls = {"n": 0}

    def flaky_upsert(tab, rows):  # type: ignore[no-untyped-def]
        if tab == "Transactions" and rows:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError(
                    "Sheets append failed for Transactions: Quota exceeded "
                    "(Write requests per minute)"
                )
        return original_upsert(tab, rows)

    monkeypatch.setattr(repo, "upsert_rows", flaky_upsert)

    first = pipeline.upload(filename=path.name, content=data)
    assert first.status == "error"
    assert "re-upload" in first.message.lower() or "failed" in first.message.lower()

    rows = repo.list_rows("StatementFiles")
    assert len(rows) == 1
    assert rows[0].status == StatementFileStatus.ERROR  # type: ignore[attr-defined]

    # Retry after fixing Sheets — must not be already_imported
    second = pipeline.upload(filename=path.name, content=data)
    assert second.status == "imported", second.message
    assert second.transactions_written >= 1
    sf = repo.list_rows("StatementFiles")[0]
    assert sf.status == StatementFileStatus.IMPORTED  # type: ignore[attr-defined]

    # Fully successful import now blocks
    third = pipeline.upload(filename=path.name, content=data)
    assert third.status == "already_imported"
