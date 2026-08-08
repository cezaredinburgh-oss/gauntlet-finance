from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from backend.engines.transfer_match import TransferMatchConfig, match_internal_transfers
from backend.tests.helpers import tx


def test_matches_exact_revolut_to_raiffeisen_pair():
    acc_rb = uuid4()
    acc_rev = uuid4()
    d = date(2026, 7, 20)
    outflow = tx(
        account_id=acc_rev,
        booking_date=d,
        amount="-10000",
        currency="CZK",
        description="Transfer to own bank",
        source_institution="Revolut",
    )
    inflow = tx(
        account_id=acc_rb,
        booking_date=d,
        amount="10000",
        currency="CZK",
        original_description="/ROC/…///URI/Sent from Revolut",
        source_institution="Raiffeisen",
        counterparty_account="2001141349/0800",
    )
    noise = tx(
        account_id=acc_rb,
        booking_date=d,
        amount="-185",
        merchant="Spotify",
        source_institution="Raiffeisen",
    )

    result = match_internal_transfers([outflow, inflow, noise])
    assert result.pairs_linked == 1
    by_id = {t.id: t for t in result.transactions}
    assert by_id[outflow.id].is_internal_transfer is True
    assert by_id[inflow.id].is_internal_transfer is True
    assert by_id[outflow.id].transfer_group_id == by_id[inflow.id].transfer_group_id
    assert by_id[noise.id].is_internal_transfer is False
    assert by_id[noise.id].transfer_group_id is None


def test_does_not_match_same_account_or_same_sign():
    acc = uuid4()
    d = date(2026, 1, 1)
    a = tx(account_id=acc, booking_date=d, amount="-100", description="Transfer")
    b = tx(account_id=acc, booking_date=d, amount="100", description="Transfer")
    result = match_internal_transfers([a, b])
    assert result.pairs_linked == 0


def test_prefers_precision_skips_weak_amount_near_match_without_hints():
    """Two unrelated legs with close amounts but no transfer hints → no link."""
    acc1, acc2 = uuid4(), uuid4()
    d = date(2026, 3, 1)
    # 0.3% difference — within rel tol but no keywords
    a = tx(
        account_id=acc1,
        booking_date=d,
        amount="-1000.00",
        currency="CZK",
        merchant="Shop A",
        description="Card payment",
        source_institution="Revolut",
    )
    b = tx(
        account_id=acc2,
        booking_date=d,
        amount="997.00",
        currency="CZK",
        merchant="Payroll",
        description="Salary",
        source_institution="Raiffeisen",
    )
    result = match_internal_transfers([a, b])
    assert result.pairs_linked == 0


def test_date_window_respected():
    acc1, acc2 = uuid4(), uuid4()
    d = date(2026, 1, 1)
    a = tx(
        account_id=acc1,
        booking_date=d,
        amount="-500",
        description="Transfer Revolut",
        source_institution="Revolut",
    )
    b = tx(
        account_id=acc2,
        booking_date=d + timedelta(days=10),
        amount="500",
        original_description="Sent from Revolut",
        source_institution="Raiffeisen",
    )
    result = match_internal_transfers(
        [a, b],
        config=TransferMatchConfig(date_window_days=3),
    )
    assert result.pairs_linked == 0


def test_rejects_spotify_vs_revolut_fx_near_amount():
    """Regression: merchant card spend must not pair with FX residue."""
    acc1, acc2 = uuid4(), uuid4()
    a = tx(
        account_id=acc1,
        booking_date=date(2026, 6, 30),
        amount="-185",
        currency="CZK",
        merchant="Spotify",
        description="Card payment Spotify",
        source_institution="Raiffeisen",
    )
    b = tx(
        account_id=acc2,
        booking_date=date(2026, 6, 29),
        amount="184.43",
        currency="CZK",
        description="Exchanged to CZK",
        source_institution="Revolut",
    )
    result = match_internal_transfers(
        [a, b],
        config=TransferMatchConfig(
            date_window_days=5,
            amount_abs_tolerance=Decimal("1.00"),
        ),
    )
    assert result.pairs_linked == 0


def test_does_not_relink_already_grouped():
    acc1, acc2 = uuid4(), uuid4()
    group = uuid4()
    d = date(2026, 1, 1)
    a = tx(
        account_id=acc1,
        booking_date=d,
        amount="-100",
        description="Transfer",
        is_internal_transfer=True,
        transfer_group_id=group,
    )
    b = tx(
        account_id=acc2,
        booking_date=d,
        amount="100",
        original_description="Sent from Revolut",
        is_internal_transfer=True,
        transfer_group_id=group,
    )
    c = tx(
        account_id=acc2,
        booking_date=d,
        amount="100",
        original_description="Sent from Revolut",
    )
    result = match_internal_transfers([a, b, c])
    # a,b already grouped; c should not steal a
    assert result.pairs_linked == 0
