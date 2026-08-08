"""Lot cost USD enrichment."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from backend.engines.fx import FXService
from backend.schema.models import AssetClass, FXRate, FXSource, InvestmentLot, LotStatus
from backend.services.lot_costs import resolve_lot_costs


def _lot(**kwargs) -> InvestmentLot:
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    base = dict(
        id=uuid4(),
        account_id=uuid4(),
        ticker="BTC",
        asset_class=AssetClass.CRYPTO,
        source="Revolut",
        acquisition_date=date(2024, 6, 1),
        quantity_opened=Decimal("1"),
        quantity_remaining=Decimal("1"),
        cost_basis_native=Decimal("23000"),
        cost_basis_czk=Decimal("23000"),
        cost_basis_usd=Decimal("0"),
        native_currency="CZK",
        status=LotStatus.OPEN,
        created_at=ts,
        updated_at=ts,
    )
    base.update(kwargs)
    return InvestmentLot(**base)


def test_resolve_czk_lot_to_usd():
    rate = FXRate(
        id=uuid4(),
        rate_date=date(2024, 6, 1),
        base_currency="USD",
        quote_currency="CZK",
        rate=Decimal("23.00"),
        source=FXSource.CNB,
        created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )
    fx = FXService(rates=[rate])
    lot = _lot()
    native, czk, usd = resolve_lot_costs(lot, fx)
    assert native == Decimal("23000")
    assert czk == Decimal("23000.00")
    assert usd == Decimal("1000.00")
