"""Lot rebuild safety: batch delete + atomic replace cannot leave double inventory."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from backend.common.timeutil import utc_now
from backend.engines.lots import LotEngine
from backend.schema.default_categories import DEFAULT_CATEGORIES
from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
    TradeSide,
)
from backend.services.import_pipeline import ImportPipeline
from backend.services.lot_rebuild import (
    event_net_by_ticker,
    open_qty_by_ticker,
    rebuild_lots_for_tickers,
)
from backend.sheets.repository import InMemorySheetsRepository
from backend.tests.helpers import TS


def _lot(
    *,
    ticker: str,
    qty: str,
    lot_id=None,
    status: LotStatus = LotStatus.OPEN,
) -> InvestmentLot:
    return InvestmentLot(
        id=lot_id or uuid4(),
        account_id=uuid4(),
        ticker=ticker,
        asset_class=AssetClass.STOCK,
        source="Revolut",
        acquisition_date=TS.date(),
        quantity_opened=Decimal(qty),
        quantity_remaining=Decimal(qty) if status == LotStatus.OPEN else Decimal("0"),
        cost_basis_native=Decimal("100"),
        cost_basis_czk=Decimal("2300"),
        cost_basis_usd=Decimal("100"),
        native_currency="USD",
        open_event_id=uuid4(),
        status=status,
        created_at=TS,
        updated_at=TS,
    )


def _ev(
    *,
    event_type: InvestmentEventType,
    ticker: str,
    qty: str,
    value: str = "100",
    eid: str | None = None,
) -> InvestmentEvent:
    return InvestmentEvent(
        id=uuid4(),
        account_id=uuid4(),
        event_type=event_type,
        event_date=TS.date(),
        event_datetime=TS,
        ticker=ticker,
        asset_class=AssetClass.STOCK,
        side=TradeSide.BUY if event_type == InvestmentEventType.BUY else TradeSide.SELL,
        quantity=Decimal(qty),
        price_native=Decimal("10"),
        native_currency="USD",
        value_native=Decimal(value),
        fees_native=Decimal("0"),
        source="Revolut",
        external_id=eid or f"ext:test:{uuid4().hex[:8]}",
        created_at=TS,
        updated_at=TS,
    )


def test_delete_by_ids_batch():
    repo = InMemorySheetsRepository()
    a, b, c = uuid4(), uuid4(), uuid4()
    repo.upsert_rows(
        "InvestmentLots",
        [
            _lot(ticker="PLTR", qty="10", lot_id=a),
            _lot(ticker="PLTR", qty="5", lot_id=b),
            _lot(ticker="COIN", qty="3", lot_id=c),
        ],
    )
    n = repo.delete_by_ids("InvestmentLots", [a, b, uuid4()])
    assert n == 2
    left = repo.list_rows("InvestmentLots")
    assert len(left) == 1
    assert left[0].id == c


def test_rebuild_then_replace_all_no_double_lots():
    """Simulates import rebuild: replace_all lots must not keep stale opens."""
    repo = InMemorySheetsRepository()
    acc = uuid4()
    buy = _ev(event_type=InvestmentEventType.BUY, ticker="PLTR", qty="110", value="1100")
    buy = buy.model_copy(update={"account_id": acc})
    sell = _ev(event_type=InvestmentEventType.SELL, ticker="PLTR", qty="29", value="500")
    sell = sell.model_copy(update={"account_id": acc})
    # Stale wrong open lots (as if prior incremental state was wrong / double inventory)
    stale = [
        _lot(ticker="PLTR", qty="50"),
        _lot(ticker="PLTR", qty="60"),
        _lot(ticker="PLTR", qty="40"),
    ]
    assert sum((l.quantity_remaining for l in stale), Decimal("0")) == Decimal("150")
    repo.upsert_rows("InvestmentLots", stale)

    engine = LotEngine(exemption_days=1095, fx=None)
    plan = rebuild_lots_for_tickers(
        existing_lots=list(repo.list_rows("InvestmentLots")),  # type: ignore[arg-type]
        existing_events=[buy, sell],
        new_events=[],
        touched_tickers={"PLTR"},
        engine=engine,
        now=utc_now(),
    )
    # Atomic replace (import path after hardening) — drops stale 150 open
    repo.replace_all_rows("InvestmentLots", plan.lots)
    open_q = open_qty_by_ticker(list(repo.list_rows("InvestmentLots")))  # type: ignore[arg-type]
    assert open_q.get("PLTR") == Decimal("81")  # 110-29 from events
    pltr_open = [
        l
        for l in repo.list_rows("InvestmentLots")
        if isinstance(l, InvestmentLot)
        and l.ticker.upper() == "PLTR"
        and l.status == LotStatus.OPEN
        and l.quantity_remaining > 0
    ]
    assert sum((l.quantity_remaining for l in pltr_open), Decimal("0")) == Decimal("81")
    # Stale lot ids must not remain
    stale_ids = {l.id for l in stale}
    remaining_ids = {l.id for l in repo.list_rows("InvestmentLots")}
    assert stale_ids.isdisjoint(remaining_ids)


def test_event_net_matches_open_after_rebuild():
    buy = _ev(event_type=InvestmentEventType.BUY, ticker="SPCX", qty="12")
    sell = _ev(event_type=InvestmentEventType.SELL, ticker="SPCX", qty="2")
    net = event_net_by_ticker([buy, sell])
    assert net["SPCX"] == Decimal("10")
    engine = LotEngine(exemption_days=1095, fx=None)
    fifo = engine.apply_events([], [buy, sell])
    oq = open_qty_by_ticker(fifo.lots)
    assert oq.get("SPCX") == Decimal("10")
