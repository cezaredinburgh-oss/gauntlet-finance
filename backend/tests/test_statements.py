from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from backend.engines.statements import (
    StatementService,
    collapse_events_by_identity,
    event_datetime_iso,
    revolut_event_external_id,
)
from backend.schema.models import InvestmentEventType, StatementFileStatus, TradeSide
from backend.sheets.codec import decode_cell, encode_cell
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import inv_event, tx

BANK = Path(__file__).resolve().parents[2] / "Bank statements"


def test_register_statement_idempotent_by_hash():
    repo = InMemorySheetsRepository()
    svc = StatementService(repo)
    data = b"hello-statement"
    first = svc.register_statement(
        filename="a.csv",
        file_bytes=data,
        institution="Raiffeisen",
        row_count=10,
        parser_key="raiffeisen_cz",
    )
    assert first.status == "new"
    assert first.statement.status == StatementFileStatus.PENDING

    # PENDING must not gate re-upload (failed/abandoned imports are retriable)
    pending_retry = svc.register_statement(
        filename="a-retry.csv",
        file_bytes=data,
        institution="Raiffeisen",
        row_count=10,
        parser_key="raiffeisen_cz",
    )
    assert pending_retry.status == "new"
    assert pending_retry.statement.id == first.statement.id

    svc.mark_imported(first.statement.id, row_count=10)
    second = svc.register_statement(
        filename="a-copy.csv",
        file_bytes=data,
        institution="Raiffeisen",
        row_count=10,
        parser_key="raiffeisen_cz",
    )
    assert second.status == "duplicate"
    assert second.statement.id == first.statement.id
    assert len(repo.list_rows("StatementFiles")) == 1


def test_mark_imported_and_duplicate_skip():
    repo = InMemorySheetsRepository()
    svc = StatementService(repo)
    reg = svc.register_statement(
        filename="x.csv",
        file_bytes=b"abc",
        institution="Revolut",
        row_count=3,
        parser_key="revolut_expenses",
    )
    imported = svc.mark_imported(reg.statement.id, row_count=3)
    assert imported is not None
    assert imported.status == StatementFileStatus.IMPORTED
    assert imported.row_count == 3


def test_dedupe_transactions_by_external_id():
    acc = uuid4()
    existing = [
        tx(
            account_id=acc,
            external_id="9295911738",
            amount="-185",
            source_institution="Raiffeisen",
            booking_date=date(2026, 7, 28),
        )
    ]
    incoming = [
        tx(
            account_id=acc,
            external_id="9295911738",
            amount="-185",
            source_institution="Raiffeisen",
            booking_date=date(2026, 7, 28),
        ),
        tx(
            account_id=acc,
            external_id="999",
            amount="-50",
            source_institution="Raiffeisen",
            booking_date=date(2026, 7, 29),
        ),
    ]
    result = StatementService.dedupe_transactions(existing, incoming)
    assert result.dropped_transactions == 1
    assert len(result.transactions) == 1
    assert result.transactions[0].external_id == "999"


def test_dedupe_keeps_same_day_same_amount_with_different_external_ids():
    """Regression: two -8000 CZK Revolut top-ups on same day must both survive."""
    acc = uuid4()
    a = tx(
        account_id=acc,
        external_id="111",
        amount="-8000",
        source_institution="Raiffeisen",
        booking_date=date(2026, 1, 3),
        description="Card payment Revolut",
    )
    b = tx(
        account_id=acc,
        external_id="222",
        amount="-8000",
        source_institution="Raiffeisen",
        booking_date=date(2026, 1, 3),
        description="Card payment Revolut",
    )
    result = StatementService.dedupe_transactions([], [a, b])
    assert result.dropped_transactions == 0
    assert len(result.transactions) == 2


def test_dedupe_soft_keeps_distinct_revolut_descriptions():
    acc = uuid4()
    a = tx(
        account_id=acc,
        amount="-100",
        currency="CZK",
        source_institution="Revolut",
        booking_date=date(2020, 7, 9),
        description="Transfer from PIOTR",
        merchant=None,
    )
    b = tx(
        account_id=acc,
        amount="-100",
        currency="CZK",
        source_institution="Revolut",
        booking_date=date(2020, 7, 9),
        description="Exchanged to EUR",
        merchant=None,
    )
    result = StatementService.dedupe_transactions([], [a, b])
    assert result.dropped_transactions == 0
    assert len(result.transactions) == 2


def test_event_soft_key_ignores_file_hash_and_norms_decimals():
    """Overlapping exports must match even with different file hashes / decimal form."""
    dt = datetime(2024, 6, 1, 12, 30, 0, tzinfo=timezone.utc)
    a = inv_event(
        ticker="DOGE",
        quantity="100.00",
        value_native="10.0",
        fees_native="0.10",
        event_date=dt.date(),
    ).model_copy(
        update={
            "event_datetime": dt,
            "original_file_hash": "a" * 64,
            "source_file_id": uuid4(),
        }
    )
    b = inv_event(
        ticker="DOGE",
        quantity="100",
        value_native="10",
        fees_native="0.1",
        event_date=dt.date(),
    ).model_copy(
        update={
            "event_datetime": dt,
            "original_file_hash": "b" * 64,
            "source_file_id": uuid4(),
        }
    )
    assert StatementService._event_soft_key(a) == StatementService._event_soft_key(b)
    result = StatementService.dedupe_events([a], [b])
    assert result.dropped_events == 1
    assert result.investment_events == []


def test_event_datetime_iso_strips_microseconds_to_sheet_wire():
    dt_us = datetime(2024, 6, 1, 12, 30, 0, 123456, tzinfo=timezone.utc)
    dt_sec = datetime(2024, 6, 1, 12, 30, 0, tzinfo=timezone.utc)
    assert event_datetime_iso(dt_us) == "2024-06-01T12:30:00Z"
    assert event_datetime_iso(dt_us) == event_datetime_iso(dt_sec)
    # Matches codec encode path
    assert event_datetime_iso(dt_us) == encode_cell(dt_us)


def test_event_soft_key_survives_sheets_datetime_roundtrip():
    """Sheets encode drops µs; soft keys must still match re-parsed twins."""
    dt_us = datetime(2024, 6, 1, 12, 30, 0, 987654, tzinfo=timezone.utc)
    fresh = inv_event(
        ticker="PLTR",
        quantity="10",
        value_native="200",
        fees_native="0",
        event_date=dt_us.date(),
    ).model_copy(update={"event_datetime": dt_us, "external_id": None})

    encoded = encode_cell(fresh.event_datetime)
    decoded = decode_cell(datetime | None, encoded)
    sheet_loaded = fresh.model_copy(
        update={"id": uuid4(), "event_datetime": decoded, "external_id": None}
    )
    assert StatementService._event_soft_key(fresh) == StatementService._event_soft_key(
        sheet_loaded
    )
    # Soft-only sheet row vs new hard external_id (µs on parse side)
    eid = revolut_event_external_id(
        event_type=InvestmentEventType.BUY.value,
        ticker="PLTR",
        event_datetime=dt_us,
        quantity=Decimal("10"),
        value_native=Decimal("200"),
        fees_native=Decimal("0"),
        currency="USD",
    )
    reparsed = fresh.model_copy(update={"id": uuid4(), "external_id": eid})
    result = StatementService.dedupe_events([sheet_loaded], [reparsed])
    assert result.dropped_events == 1


def test_event_keys_bridge_external_id_and_soft():
    """New parser rows with external_id still match older soft-only ledger rows."""
    dt = datetime(2024, 6, 1, 12, 30, 0, 111111, tzinfo=timezone.utc)
    old = inv_event(
        ticker="ADA",
        quantity="1",
        value_native="0.5",
        fees_native="0",
        event_date=dt.date(),
    ).model_copy(update={"event_datetime": dt, "external_id": None})
    # Simulate Sheets load truncating µs
    sheet_dt = decode_cell(datetime | None, encode_cell(dt))
    old_sheet = old.model_copy(update={"event_datetime": sheet_dt})
    eid = revolut_event_external_id(
        event_type=InvestmentEventType.BUY.value,
        ticker="ADA",
        event_datetime=dt,
        quantity=Decimal("1"),
        value_native=Decimal("0.5"),
        fees_native=Decimal("0"),
        currency="USD",
    )
    new = old.model_copy(update={"id": uuid4(), "external_id": eid})
    result = StatementService.dedupe_events([old_sheet], [new])
    assert result.dropped_events == 1


def test_collapse_revolut_timezone_shifted_twins():
    """Same trade re-imported with +2h datetime must collapse (soft_day key)."""
    dt_a = datetime(2026, 8, 4, 11, 30, 2, tzinfo=timezone.utc)
    dt_b = datetime(2026, 8, 4, 13, 30, 2, tzinfo=timezone.utc)
    a = inv_event(
        ticker="PLTR",
        quantity="10",
        value_native="1449.96",
        fees_native="0",
        event_date=dt_a.date(),
    ).model_copy(
        update={
            "event_type": InvestmentEventType.SELL,
            "side": TradeSide.SELL,
            "event_datetime": dt_a,
            "external_id": revolut_event_external_id(
                event_type="Sell",
                ticker="PLTR",
                event_datetime=dt_a,
                quantity=Decimal("10"),
                value_native=Decimal("1449.96"),
                fees_native=Decimal("0"),
                currency="USD",
            ),
            "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
        }
    )
    b = a.model_copy(
        update={
            "id": uuid4(),
            "event_datetime": dt_b,
            "external_id": revolut_event_external_id(
                event_type="Sell",
                ticker="PLTR",
                event_datetime=dt_b,
                quantity=Decimal("10"),
                value_native=Decimal("1449.96"),
                fees_native=Decimal("0"),
                currency="USD",
            ),
            "created_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
        }
    )
    # Different value same day — real second trade, must survive
    c = a.model_copy(
        update={
            "id": uuid4(),
            "event_datetime": dt_b.replace(hour=17),
            "value_native": Decimal("1639.62"),
            "external_id": revolut_event_external_id(
                event_type="Sell",
                ticker="PLTR",
                event_datetime=dt_b.replace(hour=17),
                quantity=Decimal("10"),
                value_native=Decimal("1639.62"),
                fees_native=Decimal("0"),
                currency="USD",
            ),
        }
    )
    keep, removed = collapse_events_by_identity([a, b, c])
    assert removed == 1
    assert len(keep) == 2
    assert a.id in {e.id for e in keep}  # earlier twin kept
    assert c.id in {e.id for e in keep}


def test_collapse_events_bridges_soft_only_and_hard():
    """Repair union-find must collapse mixed soft-only + external_id twins."""
    dt = datetime(2024, 6, 1, 12, 30, 0, 5, tzinfo=timezone.utc)
    soft_only = inv_event(
        ticker="PATH",
        quantity="3",
        value_native="30",
        fees_native="0",
        event_date=dt.date(),
    ).model_copy(
        update={
            "event_datetime": decode_cell(datetime | None, encode_cell(dt)),
            "external_id": None,
            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }
    )
    eid = revolut_event_external_id(
        event_type=InvestmentEventType.BUY.value,
        ticker="PATH",
        event_datetime=dt,
        quantity=Decimal("3"),
        value_native=Decimal("30"),
        fees_native=Decimal("0"),
        currency="USD",
    )
    hard_row = soft_only.model_copy(
        update={
            "id": uuid4(),
            "external_id": eid,
            "event_datetime": dt,
            "created_at": datetime(2024, 6, 1, tzinfo=timezone.utc),
        }
    )
    # Distinct third event must survive
    other = inv_event(
        ticker="TSLA",
        quantity="1",
        value_native="100",
        event_date=dt.date(),
    ).model_copy(update={"event_datetime": dt})

    keep, removed = collapse_events_by_identity([soft_only, hard_row, other])
    assert removed == 1
    assert len(keep) == 2
    assert soft_only.id in {e.id for e in keep}  # earliest kept
    assert other.id in {e.id for e in keep}


def test_revolut_expense_old_balance_hash_soft_bridges_to_new():
    """Old Balance-including rev: id vs new Balance-free id → soft match drops."""
    acc = uuid4()
    notes = "Card Payment | Current | COMPLETED | completed=2026-01-13T10:01:00+00:00"
    old = tx(
        account_id=acc,
        external_id="rev:oldbalancehash00000001",
        amount="-12.34",
        currency="USD",
        source_institution="Revolut",
        booking_date=date(2026, 1, 13),
        description="Shop",
        original_description="Shop",
    ).model_copy(update={"notes": notes})
    new = tx(
        account_id=acc,
        external_id="rev:newnobalancehash0000002",
        amount="-12.34",
        currency="USD",
        source_institution="Revolut",
        booking_date=date(2026, 1, 13),
        description="Shop",
        original_description="Shop",
    ).model_copy(
        update={"notes": notes.replace("+00:00", "Z")}  # normalized form still matches
    )
    result = StatementService.dedupe_transactions([old], [new])
    assert result.dropped_transactions == 1
    assert result.transactions == []


def test_revolut_same_day_same_amount_different_times_kept():
    """Distinct hard rev: ids with different completed= times must not soft-collapse."""
    acc = uuid4()
    a = tx(
        account_id=acc,
        external_id="rev:aaaaaaaaaaaaaaaaaaaaaaa1",
        amount="-100",
        currency="CZK",
        source_institution="Revolut",
        booking_date=date(2021, 4, 10),
        description="Exchanged to EUR",
        original_description="Exchanged to EUR",
    ).model_copy(
        update={
            "notes": "Exchange | Current | COMPLETED | completed=2021-04-10T09:00:00+00:00"
        }
    )
    b = tx(
        account_id=acc,
        external_id="rev:bbbbbbbbbbbbbbbbbbbbbbb2",
        amount="-100",
        currency="CZK",
        source_institution="Revolut",
        booking_date=date(2021, 4, 10),
        description="Exchanged to EUR",
        original_description="Exchanged to EUR",
    ).model_copy(
        update={
            "notes": "Exchange | Current | COMPLETED | completed=2021-04-10T15:30:00+00:00"
        }
    )
    assert StatementService._tx_soft_key(a) != StatementService._tx_soft_key(b)
    result = StatementService.dedupe_transactions([], [a, b])
    assert result.dropped_transactions == 0
    assert len(result.transactions) == 2


def test_raiffeisen_hard_ids_not_soft_collapsed():
    """Non-Revolut hard IDs remain hard-only (no soft over-collapse)."""
    acc = uuid4()
    a = tx(
        account_id=acc,
        external_id="111",
        amount="-8000",
        source_institution="Raiffeisen",
        booking_date=date(2026, 1, 3),
        description="Card payment Revolut",
    )
    b = tx(
        account_id=acc,
        external_id="222",
        amount="-8000",
        source_institution="Raiffeisen",
        booking_date=date(2026, 1, 3),
        description="Card payment Revolut",
    )
    keys_a = StatementService._tx_keys(a)
    keys_b = StatementService._tx_keys(b)
    assert all(k.startswith("ext:") for k in keys_a)
    assert keys_a.isdisjoint(keys_b)


def test_crypto_tax_year_after_all_time_dedupes_heavily():
    """
    Golden: tax-year Revolut crypto after all-time must drop ≥98% of tax events.
    Measured on current fixtures ≈ 385/388 dropped, ~3 kept.
    """
    all_time = BANK / "All time crypto revolut.csv"
    tax = BANK / "Tax year test Revolut crypto_.csv"
    if not all_time.is_file() or not tax.is_file():
        pytest.skip("Bank statements fixtures not present")

    from backend.parsers.revolut_crypto import parse_revolut_crypto

    acc = uuid4()
    existing = parse_revolut_crypto(
        all_time.read_text(encoding="utf-8-sig"),
        account_ids={"default": acc},
        file_hash="1" * 64,
    ).investment_events
    incoming = parse_revolut_crypto(
        tax.read_text(encoding="utf-8-sig"),
        account_ids={"default": acc},
        file_hash="2" * 64,
    ).investment_events
    assert incoming, "tax-year crypto fixture produced no events"
    result = StatementService.dedupe_events(existing, incoming)
    drop_rate = result.dropped_events / len(incoming)
    assert drop_rate >= 0.98, (
        f"expected ≥98% drop, got {result.dropped_events}/{len(incoming)} "
        f"({drop_rate:.1%}) kept={len(result.investment_events)}"
    )
    # Sanity: measured ~3 true new rows on current exports
    assert len(result.investment_events) <= max(20, int(0.05 * len(incoming)))


def test_stocks_soft_only_codec_roundtrip_still_dedupes():
    """
    Golden: sheet-loaded soft-only all-time stocks vs tax-year re-parse.
    Simulates Sheets µs truncation without hard external_id on existing rows.
    """
    all_time = BANK / "All time stocks revolut.csv"
    tax = BANK / "Tax year test Revolut stocks_.csv"
    if not all_time.is_file() or not tax.is_file():
        pytest.skip("Bank statements fixtures not present")

    from backend.parsers.revolut_stocks import parse_revolut_stocks

    acc = uuid4()
    existing_raw = parse_revolut_stocks(
        all_time.read_text(encoding="utf-8-sig"),
        account_ids={"default": acc},
        file_hash="1" * 64,
    ).investment_events
    # Strip hard ids and round-trip datetime through codec (Sheets path)
    existing = []
    for e in existing_raw:
        dt = e.event_datetime
        if dt is not None:
            dt = decode_cell(datetime | None, encode_cell(dt))
        existing.append(
            e.model_copy(update={"external_id": None, "event_datetime": dt})
        )
    incoming = parse_revolut_stocks(
        tax.read_text(encoding="utf-8-sig"),
        account_ids={"default": acc},
        file_hash="2" * 64,
    ).investment_events
    assert incoming
    result = StatementService.dedupe_events(existing, incoming)
    drop_rate = result.dropped_events / len(incoming)
    assert drop_rate >= 0.95, (
        f"expected ≥95% drop after codec round-trip, got "
        f"{result.dropped_events}/{len(incoming)} ({drop_rate:.1%})"
    )
