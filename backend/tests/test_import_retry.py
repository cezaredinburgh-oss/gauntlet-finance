"""Failed imports must not permanently gate re-upload of the same SHA-256."""

from __future__ import annotations

import threading
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from backend.engines.lots import LotEngine
from backend.engines.statements import StatementService
from backend.schema.models import (
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    StatementFileStatus,
)
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


def _open_qty_by_ticker(lots: list[InvestmentLot]) -> dict[str, Decimal]:
    from backend.schema.models import LotStatus

    out: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for lot in lots:
        if lot.archived:
            continue
        if lot.status != LotStatus.OPEN or lot.quantity_remaining <= 0:
            continue
        out[(lot.ticker or "").upper()] += lot.quantity_remaining
    return dict(out)


def test_partial_events_without_lots_rebuild_on_retry():
    """
    Simulate ERROR after writing InvestmentEvents but no lots.
    Re-upload same file → lots consistent with FIFO on all events.
    """
    repo = InMemorySheetsRepository()
    seed_minimal(repo)
    path = FIXTURES / "revolut_crypto_sample.csv"
    data = path.read_bytes()
    pipeline = ImportPipeline(repo)

    # First attempt: write events, then fail on lots
    original_upsert = repo.upsert_rows

    def upsert_fail_lots(tab, rows):  # type: ignore[no-untyped-def]
        if tab == "InvestmentLots" and rows:
            raise RuntimeError("Sheets append failed for InvestmentLots: quota")
        return original_upsert(tab, rows)

    pipeline.repo.upsert_rows = upsert_fail_lots  # type: ignore[method-assign]
    first = pipeline.upload(filename=path.name, content=data)
    assert first.status == "error", first.message

    events_after_fail = [
        r for r in repo.list_rows("InvestmentEvents") if isinstance(r, InvestmentEvent)
    ]
    lots_after_fail = [
        r for r in repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)
    ]
    assert events_after_fail, "events should persist before lots fail"
    assert lots_after_fail == []

    non_alloc = [
        e
        for e in events_after_fail
        if e.event_type != InvestmentEventType.LOT_ALLOCATION
    ]
    expected = LotEngine(exemption_days=1095).apply_events(
        [],
        [e.model_copy(update={"lot_id": None}) for e in non_alloc],
    )
    expected_open = _open_qty_by_ticker(expected.lots)

    # Retry — must rebuild lots from all existing events (new events deduped)
    pipeline.repo.upsert_rows = original_upsert  # type: ignore[method-assign]
    second = pipeline.upload(filename=path.name, content=data)
    assert second.status == "imported", second.message

    lots = [
        r for r in repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)
    ]
    got_open = _open_qty_by_ticker(lots)
    assert got_open, "retry must create lots from existing events"
    for ticker, qty in expected_open.items():
        assert ticker in got_open, f"missing open lot for {ticker}"
        assert got_open[ticker] == qty, f"{ticker}: {got_open[ticker]} != {qty}"

    sells = [
        e
        for e in repo.list_rows("InvestmentEvents")
        if isinstance(e, InvestmentEvent) and e.event_type == InvestmentEventType.SELL
    ]
    allocs = [
        e
        for e in repo.list_rows("InvestmentEvents")
        if isinstance(e, InvestmentEvent)
        and e.event_type == InvestmentEventType.LOT_ALLOCATION
    ]
    if sells:
        assert allocs, "FIFO should create LotAllocation children for sells"

    sf = repo.list_rows("StatementFiles")[0]
    assert sf.status == StatementFileStatus.IMPORTED  # type: ignore[attr-defined]

    third = pipeline.upload(filename=path.name, content=data)
    assert third.status == "already_imported"


def test_import_lock_serializes_concurrent_uploads():
    """Two threads uploading different files must not interleave mid-pipeline."""
    repo = InMemorySheetsRepository()
    seed_minimal(repo)
    path_a = FIXTURES / "raiffeisen_sample.csv"
    path_b = FIXTURES / "revolut_expenses_sample.csv"
    data_a = path_a.read_bytes()
    data_b = path_b.read_bytes()
    pipeline = ImportPipeline(repo)

    results: list = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker(name: str, filename: str, content: bytes) -> None:
        try:
            barrier.wait(timeout=5)
            r = pipeline.upload(filename=filename, content=content)
            results.append((name, r))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(
        target=worker, args=("a", path_a.name, data_a), daemon=True
    )
    t2 = threading.Thread(
        target=worker, args=("b", path_b.name, data_b), daemon=True
    )
    t1.start()
    t2.start()
    t1.join(timeout=60)
    t2.join(timeout=60)
    assert not errors, errors
    assert len(results) == 2
    statuses = {name: r.status for name, r in results}
    assert statuses["a"] == "imported", statuses
    assert statuses["b"] == "imported", statuses
    # No double statement rows per hash
    sfs = repo.list_rows("StatementFiles")
    assert len(sfs) == 2
