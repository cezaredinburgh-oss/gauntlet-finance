from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from backend.parsers.revolut_crypto import (
    net_revolut_crypto_buy_quantity,
    parse_revolut_crypto,
)
from backend.schema.models import AssetClass, InvestmentEventType

FIXTURES = Path(__file__).parent / "fixtures"


def test_net_revolut_crypto_buy_quantity_metal_fee():
    # 0.99% Metal fee: 29.70 / 3000
    net, rate = net_revolut_crypto_buy_quantity(
        Decimal("1480.19651801"),
        Decimal("3000"),
        Decimal("29.70"),
    )
    assert rate == Decimal("0.0099")
    assert net == Decimal("1480.19651801") * Decimal("0.9901")


def test_net_revolut_crypto_buy_quantity_zero_fee():
    net, rate = net_revolut_crypto_buy_quantity(
        Decimal("26"), Decimal("111.84"), Decimal("0")
    )
    assert net == Decimal("26")
    assert rate == Decimal("0")


def test_parse_revolut_crypto_mixed_ccy_and_empty_staking_reward():
    text = (FIXTURES / "revolut_crypto_sample.csv").read_text(encoding="utf-8")
    account_id = uuid4()
    result = parse_revolut_crypto(
        text,
        account_ids={"default": account_id},
        file_hash="c" * 64,
    )
    assert result.parser_key == "revolut_crypto"
    assert result.row_count == 6
    types = {e.event_type for e in result.investment_events}
    assert InvestmentEventType.BUY in types
    assert InvestmentEventType.SELL in types
    assert InvestmentEventType.STAKE in types
    assert InvestmentEventType.STAKING_REWARD in types

    czk_buy = next(
        e
        for e in result.investment_events
        if e.ticker == "ENJ" and e.native_currency == "CZK"
    )
    assert czk_buy.price_native == Decimal("94.75")
    assert czk_buy.value_native == Decimal("4263.92")
    assert czk_buy.fees_native == Decimal("127.92")
    # Gross 45, fee rate 127.92/4263.92 → net qty
    expected_net = Decimal("45") * (
        Decimal("1") - Decimal("127.92") / Decimal("4263.92")
    )
    assert czk_buy.quantity == expected_net
    assert "revolut_buy_fee_net" in (czk_buy.notes or "")
    assert "gross_qty=45" in (czk_buy.notes or "")

    usd_buy = next(
        e
        for e in result.investment_events
        if e.ticker == "ENJ" and e.native_currency == "USD"
    )
    # 100 * (1 - 3.80/294.96)
    assert usd_buy.quantity == Decimal("100") * (
        Decimal("1") - Decimal("3.80") / Decimal("294.96")
    )
    # "Nov 18, 2021, 4:22:55 PM" Europe/Prague CET → 15:22:55 UTC
    assert usd_buy.event_datetime == datetime(
        2021, 11, 18, 15, 22, 55, tzinfo=timezone.utc
    )

    sell = next(
        e for e in result.investment_events if e.event_type == InvestmentEventType.SELL
    )
    # Sells stay at statement quantity (not fee-netted)
    assert sell.quantity == Decimal("0.11655496")

    reward = next(
        e
        for e in result.investment_events
        if e.event_type == InvestmentEventType.STAKING_REWARD
    )
    assert reward.ticker == "ADA"
    assert reward.price_native is None
    assert reward.value_native is None
    assert reward.fees_native == Decimal("0")
    assert reward.quantity == Decimal("0.643013")

    # Buys + staking reward open lots; sells/stakes do not invent sale lots
    assert len(result.investment_lots) == 4
    assert all(lot.asset_class == AssetClass.CRYPTO for lot in result.investment_lots)
    ada_lot = next(lot for lot in result.investment_lots if lot.ticker == "ADA")
    assert ada_lot.cost_basis_native == Decimal("0")
    assert ada_lot.acquisition_date.isoformat() == "2024-11-18"

    # Stable external_id on every event (file-hash independent)
    assert all(
        e.external_id and e.external_id.startswith("ext:Revolut:")
        for e in result.investment_events
    )
    ids = [e.external_id for e in result.investment_events]
    assert len(ids) == len(set(ids))


def test_doge_fee_net_sum_matches_broker_balance():
    """Sum of fee-netted DOGE buys ≈ Revolut app total balance."""
    path = (
        Path(__file__).resolve().parents[2]
        / "Bank statements"
        / "Revolut audit recheck for doge and xrp.csv"
    )
    if not path.exists():
        path = (
            Path(__file__).resolve().parents[2]
            / "Bank statements"
            / "All time crypto revolut.csv"
        )
    if not path.exists():
        pytest.skip("Bank statements fixtures not present")
    text = path.read_text(encoding="utf-8-sig")
    result = parse_revolut_crypto(
        text,
        account_ids={"default": uuid4()},
        file_hash="d" * 64,
    )
    doge_buys = [
        e
        for e in result.investment_events
        if e.ticker == "DOGE" and e.event_type == InvestmentEventType.BUY
    ]
    total = sum((e.quantity or Decimal("0") for e in doge_buys), Decimal("0"))
    # Broker UI: 39518.1731903 — model lands within 0.1
    assert abs(total - Decimal("39518.1731903")) < Decimal("0.1")
