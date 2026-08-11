"""End-to-end ImportPipeline tests (InMemory repo, fixtures)."""

from __future__ import annotations

from pathlib import Path

from backend.schema.models import (
    InvestmentEvent,
    InvestmentLot,
    StatementFileStatus,
    Transaction,
)
from backend.services.import_pipeline import ImportPipeline
from backend.scripts.seed_dev_repo import seed_minimal
from backend.sheets.repository import InMemorySheetsRepository

FIXTURES = Path(__file__).parent / "fixtures"


def test_e2e_revolut_crypto_import_then_already_imported():
    repo = InMemorySheetsRepository()
    seed_minimal(repo)
    path = FIXTURES / "revolut_crypto_sample.csv"
    data = path.read_bytes()
    pipeline = ImportPipeline(repo)

    first = pipeline.upload(filename=path.name, content=data)
    assert first.status == "imported", first.message
    assert first.parser_key == "revolut_crypto"
    assert first.events_written >= 1
    assert first.lots_written >= 1

    events = [
        r for r in repo.list_rows("InvestmentEvents") if isinstance(r, InvestmentEvent)
    ]
    lots = [
        r for r in repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)
    ]
    assert events
    assert lots

    n_events = len(events)
    n_lots = len(lots)

    second = pipeline.upload(filename=path.name, content=data)
    assert second.status == "already_imported"
    assert second.events_written == 0
    assert second.transactions_written == 0

    # Idempotent: no new ledger rows
    assert (
        len(
            [
                r
                for r in repo.list_rows("InvestmentEvents")
                if isinstance(r, InvestmentEvent)
            ]
        )
        == n_events
    )
    assert (
        len(
            [r for r in repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)]
        )
        == n_lots
    )
    sf = repo.list_rows("StatementFiles")[0]
    assert sf.status == StatementFileStatus.IMPORTED  # type: ignore[attr-defined]


def test_e2e_expenses_import_then_already_imported():
    repo = InMemorySheetsRepository()
    seed_minimal(repo)
    path = FIXTURES / "revolut_expenses_sample.csv"
    data = path.read_bytes()
    pipeline = ImportPipeline(repo)

    first = pipeline.upload(filename=path.name, content=data)
    assert first.status == "imported", first.message
    assert first.transactions_written >= 1

    txs = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    n_tx = len(txs)
    assert n_tx >= 1

    second = pipeline.upload(filename=path.name, content=data)
    assert second.status == "already_imported"
    assert (
        len([r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)])
        == n_tx
    )
