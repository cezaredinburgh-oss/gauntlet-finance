"""Deterministic Ask Grok+ preclassify (no xAI)."""

from __future__ import annotations

from backend.schema.default_categories import (
    CAT_BANK_FEES,
    CAT_CASH_WITHDRAWAL,
    CAT_GROCERIES,
    CAT_INTERNAL,
    CAT_LOANS,
    CAT_TAXI,
    DEFAULT_CATEGORIES,
)
from backend.services.ai_categorize import MerchantCluster, _category_catalog
from backend.services.vendor_preclassify import (
    preclassify_clusters,
    unwrap_vendor_label,
)


def _cl(label: str, key: str | None = None, count: int = 3) -> MerchantCluster:
    return MerchantCluster(
        merchant_key=key or f"d:{label.lower()}",
        label=label,
        amount_sign="out",
        currency="CZK",
        sample_count=count,
        transaction_ids=["a", "b"],
    )


def _catalog() -> list[dict[str, str]]:
    return _category_catalog(list(DEFAULT_CATEGORIES))


def test_unwrap_card_payment():
    assert unwrap_vendor_label("Card payment — Lidl; Praha 3; CZE") == "Lidl"
    assert (
        unwrap_vendor_label("Card payment Google Pay — ARTIC BAKEHOUSE; PRAHA")
        == "ARTIC BAKEHOUSE"
    )


def test_pocket_and_fx_are_internal():
    cat = _catalog()
    r = preclassify_clusters(
        [
            _cl("To pocket CZK Purchase vault from CZK"),
            _cl("Exchanged to EUR"),
            _cl("Top-up by *9318"),
        ],
        cat,
    )
    assert [g.category_id for g in r.resolved] == [str(CAT_INTERNAL)] * 3
    assert r.leftovers == []


def test_cash_loan_fee_rules():
    cat = _catalog()
    r = preclassify_clusters(
        [
            _cl("Cash withdrawal at Csob 1134 Praha 2", key="m:cash withdrawal at csob"),
            _cl("Loan repayment — Credit instalment Minutova pujc"),
            _cl("Alert fee — Transaction information"),
        ],
        cat,
    )
    ids = {g.category_id for g in r.resolved}
    assert str(CAT_CASH_WITHDRAWAL) in ids
    assert str(CAT_LOANS) in ids
    assert str(CAT_BANK_FEES) in ids
    assert r.leftovers == []


def test_known_merchant_and_unwrapped_lidl():
    cat = _catalog()
    r = preclassify_clusters(
        [
            _cl("Albert", key="m:albert"),
            _cl("Lime", key="m:lime"),
            _cl("Card payment — Lidl; Praha 3; CZE", key="d:card payment — lidl"),
        ],
        cat,
    )
    by_label = {g.cluster.label: g for g in r.resolved}
    assert by_label["Albert"].category_id == str(CAT_GROCERIES)
    assert by_label["Lime"].category_id == str(CAT_TAXI)
    assert by_label["Card payment — Lidl; Praha 3; CZE"].category_id == str(CAT_GROCERIES)
    assert r.leftovers == []


def test_unknown_stays_leftover():
    cat = _catalog()
    mystery = _cl("Obscure XYZ s.r.o.", key="m:obscure xyz s.r.o.")
    r = preclassify_clusters([mystery], cat)
    assert r.resolved == []
    assert r.leftovers == [mystery]
