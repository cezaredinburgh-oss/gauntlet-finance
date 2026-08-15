"""Core pack tags; never writes category_id."""

from __future__ import annotations

from backend.engines.core_pack import match_core_pack, tag_transaction, tag_transactions
from backend.schema.default_categories import (
    CAT_BANK_FEES,
    CAT_CASH_WITHDRAWAL,
    CAT_CRYPTO_FUND,
    CAT_INTERNAL,
    CAT_RESTAURANTS,
    CAT_SPOTIFY,
    DEFAULT_CATEGORIES,
)
from backend.tests.helpers import tx


def test_does_not_set_category_id():
    t = tx(merchant="Spotify")
    out = tag_transaction(t, list(DEFAULT_CATEGORIES))
    assert out.category_id is None
    assert out.suggest_category_id == CAT_SPOTIFY
    assert out.suggest_source == "core"
    assert not out.is_internal_transfer


def test_pots_flag_internal_without_category():
    t = tx(description="To pocket CZK Purchase vault from CZK")
    out = tag_transaction(t, list(DEFAULT_CATEGORIES))
    assert out.category_id is None
    assert out.is_internal_transfer is True
    assert out.suggest_category_id == CAT_INTERNAL


def test_digital_assets_flags_crypto_funding():
    t = tx(description="Revolut Digital Assets Europe Ltd")
    out = tag_transaction(t, list(DEFAULT_CATEGORIES))
    assert out.category_id is None
    assert out.is_internal_transfer is True
    assert out.suggest_category_id == CAT_CRYPTO_FUND


def test_top_up_is_not_firmware():
    hit = match_core_pack("Top-up by *9318", "", list(DEFAULT_CATEGORIES))
    assert hit is None


def test_unknown_shop_not_tagged():
    t = tx(merchant="Albert")
    out = tag_transaction(t, list(DEFAULT_CATEGORIES))
    assert out.suggest_category_id is None
    assert out.category_id is None


def test_mcdonalds_exact_and_atm():
    shop = tag_transaction(tx(merchant="McDonald's"), list(DEFAULT_CATEGORIES))
    atm = tag_transaction(tx(description="Cash withdrawal ATM Praha"), list(DEFAULT_CATEGORIES))
    fee = tag_transaction(tx(description="Metal plan fee"), list(DEFAULT_CATEGORIES))
    assert shop.suggest_category_id == CAT_RESTAURANTS
    assert atm.suggest_category_id == CAT_CASH_WITHDRAWAL
    assert fee.suggest_category_id == CAT_BANK_FEES
    tagged, n_tag, n_flag = tag_transactions(
        [tx(merchant="Spotify"), tx(merchant="Obscure")],
        list(DEFAULT_CATEGORIES),
    )
    assert n_tag == 1
    assert n_flag == 0
    assert tagged[0].suggest_category_id == CAT_SPOTIFY
