from __future__ import annotations

from backend.engines.categorize import CategoryEngine, apply_category_rules
from backend.schema.models import LifeDomain, MatchField, MatchType, Necessity
from backend.tests.helpers import category, rule, tx


def test_spotify_rule_and_priority():
    cat_subs = category(
        name="Subscriptions",
        necessity=Necessity.DISCRETIONARY,
        life_domain=LifeDomain.SUBSCRIPTIONS,
    )
    cat_spotify = category(
        name="Spotify",
        necessity=Necessity.DISCRETIONARY,
        life_domain=LifeDomain.SUBSCRIPTIONS,
    )
    rules = [
        rule(
            priority=20,
            category_id=cat_subs.id,
            match_field=MatchField.MERCHANT,
            match_type=MatchType.CONTAINS,
            match_value="Spot",
        ),
        rule(
            priority=10,
            category_id=cat_spotify.id,
            match_field=MatchField.MERCHANT,
            match_type=MatchType.CONTAINS,
            match_value="Spotify",
        ),
    ]
    t = tx(merchant="Spotify", amount="-185")
    out = apply_category_rules(t, rules)
    assert out.category_id == cat_spotify.id


def test_internal_transfer_flag_from_rule():
    cat_int = category(
        name="Internal transfer",
        necessity=Necessity.FIXED,
        life_domain=LifeDomain.TRANSFERS,
        is_transfer=True,
    )
    rules = [
        rule(
            priority=5,
            category_id=cat_int.id,
            match_field=MatchField.ORIGINAL_DESCRIPTION,
            match_type=MatchType.CONTAINS,
            match_value="Sent from Revolut",
            set_internal_transfer=True,
            institution_scope="Raiffeisen",
        )
    ]
    t = tx(
        amount="10000",
        original_description="/ROC/x///URI/Sent from Revolut",
        source_institution="Raiffeisen",
    )
    out = apply_category_rules(t, rules)
    assert out.category_id == cat_int.id
    assert out.is_internal_transfer is True


def test_override_blocks_rules():
    cat = category(name="Other")
    rules = [
        rule(
            priority=1,
            category_id=cat.id,
            match_value="Spotify",
            match_field=MatchField.MERCHANT,
        )
    ]
    locked = tx(merchant="Spotify", category_override=True, category_id=None)
    out = apply_category_rules(locked, rules)
    assert out.category_id is None
    assert out.category_override is True


def test_revolut_digital_assets_transfer_detector():
    from backend.services.categorization import is_revolut_digital_assets_transfer

    assert is_revolut_digital_assets_transfer(
        tx(
            description="Transfer to Revolut Digital Assets Europe Ltd",
            amount="-11000",
            currency="CZK",
            source_institution="Revolut",
        )
    )
    assert is_revolut_digital_assets_transfer(
        tx(
            description="Transfer from Revolut Digital Assets Europe Ltd",
            amount="500",
            currency="USD",
            source_institution="Revolut",
        )
    )
    assert is_revolut_digital_assets_transfer(
        tx(
            description="Exchange",
            original_description="Transfer to Revolut Digital Assets Europe Ltd",
            amount="-700",
            currency="USD",
        )
    )
    # Unrelated external / peer transfers
    assert not is_revolut_digital_assets_transfer(
        tx(description="Transfer to Sylwia", amount="-500", currency="CZK")
    )
    assert not is_revolut_digital_assets_transfer(
        tx(description="To investment account", amount="-1000", currency="CZK")
    )


def test_repair_revolut_digital_assets_transfers():
    from backend.schema.default_categories import CAT_CRYPTO_FUND, CAT_EXTERNAL_XFER
    from backend.services.categorization import repair_revolut_digital_assets_transfers
    from backend.sheets.repository import InMemorySheetsRepository

    repo = InMemorySheetsRepository()
    to_da = tx(
        description="Transfer to Revolut Digital Assets Europe Ltd",
        amount="-11000",
        currency="CZK",
        category_id=CAT_EXTERNAL_XFER,
        is_internal_transfer=False,
    )
    from_da = tx(
        description="Transfer from Revolut Digital Assets Europe Ltd",
        amount="500",
        currency="USD",
        category_id=None,
        is_internal_transfer=False,
    )
    peer = tx(
        description="Transfer to Sylwia",
        amount="-200",
        currency="CZK",
        category_id=CAT_EXTERNAL_XFER,
    )
    override = tx(
        description="Transfer to Revolut Digital Assets Europe Ltd",
        amount="-100",
        currency="USD",
        category_id=CAT_EXTERNAL_XFER,
        category_override=True,
    )
    already = tx(
        description="Transfer to Revolut Digital Assets Europe Ltd",
        amount="-50",
        currency="EUR",
        category_id=CAT_CRYPTO_FUND,
        is_internal_transfer=True,
    )
    repo.upsert_rows("Transactions", [to_da, from_da, peer, override, already])

    stats = repair_revolut_digital_assets_transfers(repo, skip_user_overrides=True)
    assert stats["matched"] == 4  # to, from, override, already
    assert stats["transactions_updated"] == 2  # to + from
    assert stats["transactions_already_ok"] == 1
    assert stats["transactions_skipped_override"] == 1
    assert stats["rules_updated"] >= 1

    by_id = {t.id: t for t in repo.list_rows("Transactions")}
    assert by_id[to_da.id].is_internal_transfer is True
    assert by_id[to_da.id].category_id == CAT_CRYPTO_FUND
    assert by_id[from_da.id].is_internal_transfer is True
    assert by_id[from_da.id].category_id == CAT_CRYPTO_FUND
    assert by_id[peer.id].is_internal_transfer is False
    assert by_id[peer.id].category_id == CAT_EXTERNAL_XFER
    assert by_id[override.id].is_internal_transfer is False
    assert by_id[override.id].category_id == CAT_EXTERNAL_XFER

    # Idempotent second pass
    stats2 = repair_revolut_digital_assets_transfers(repo)
    assert stats2["transactions_updated"] == 0
    assert stats2["transactions_already_ok"] == 3  # to + from + already


def test_own_account_bank_transfer_detector():
    """Institution-generic own-account detection (no personal-name heuristics)."""
    from backend.services.categorization import is_own_account_bank_transfer

    assert is_own_account_bank_transfer(
        tx(
            description="Card payment — Revolut**1708*; Dublin; IRL — Revolut",
            merchant="Revolut",
            amount="-15000",
            currency="CZK",
            source_institution="Raiffeisen",
        )
    )
    assert is_own_account_bank_transfer(
        tx(
            description="Incoming payment",
            original_description="/URI/Sent from Revolut",
            amount="10000",
            currency="CZK",
            source_institution="Raiffeisen",
        )
    )
    assert is_own_account_bank_transfer(
        tx(
            description="Between own accounts",
            amount="-100",
            currency="EUR",
            source_institution="Revolut",
        )
    )
    # Exclusions: bills must not count as own-account pot moves
    assert not is_own_account_bank_transfer(
        tx(
            description="Standing order — Insurance premium — Allianz",
            merchant="Allianz",
            amount="-1887",
            currency="CZK",
            source_institution="Raiffeisen",
        )
    )
    assert not is_own_account_bank_transfer(
        tx(
            description="Card payment — supermarket",
            merchant="Tesco",
            amount="-500",
            currency="CZK",
            source_institution="Raiffeisen",
        )
    )


def test_apply_match_reclassifies_existing_non_override():
    """Global apply-match should re-tag External→Utilities style history."""
    from backend.schema.default_categories import CAT_EXTERNAL_XFER, CAT_UTILITIES
    from backend.services.categorization import apply_match_to_all_transactions
    from backend.sheets.repository import InMemorySheetsRepository
    from backend.schema.models import Category, LifeDomain, Necessity
    from backend.tests.helpers import TS

    repo = InMemorySheetsRepository()
    util = Category(
        id=CAT_UTILITIES,
        name="Utilities",
        necessity=Necessity.FIXED,
        life_domain=LifeDomain.HOUSING,
        is_income=False,
        is_transfer=False,
        created_at=TS,
        updated_at=TS,
    )
    ext = Category(
        id=CAT_EXTERNAL_XFER,
        name="External transfer",
        necessity=Necessity.FIXED,
        life_domain=LifeDomain.TRANSFERS,
        is_income=False,
        is_transfer=True,
        created_at=TS,
        updated_at=TS,
    )
    repo.upsert_rows("Categories", [util, ext])
    t1 = tx(merchant="Vodafone", description="To Vodafone", category_id=CAT_EXTERNAL_XFER)
    t2 = tx(merchant="Vodafone CZ", description="bill", category_id=None)
    t3 = tx(
        merchant="Vodafone",
        description="manual",
        category_id=CAT_EXTERNAL_XFER,
        category_override=True,
    )
    t4 = tx(merchant="T-Mobile", description="other", category_id=CAT_EXTERNAL_XFER)
    repo.upsert_rows("Transactions", [t1, t2, t3, t4])

    stats = apply_match_to_all_transactions(
        repo,
        category_id=CAT_UTILITIES,
        match_field="merchant",
        match_type="contains",
        match_value="Vodafone",
        mode="reclassify_non_override",
        mark_override=True,
    )
    assert stats["matched"] == 3
    assert stats["updated"] == 2  # t1 + t2; t3 override skipped
    by_id = {t.id: t for t in repo.list_rows("Transactions")}
    assert by_id[t1.id].category_id == CAT_UTILITIES
    assert by_id[t2.id].category_id == CAT_UTILITIES
    assert by_id[t3.id].category_id == CAT_EXTERNAL_XFER
    assert by_id[t4.id].category_id == CAT_EXTERNAL_XFER


def test_exchanged_to_and_pocket_withdrawal_are_internal():
    """Spare-change FX and vault withdrawals must not count as spend."""
    from backend.schema.default_categories import CAT_INTERNAL
    from backend.services.categorization import _KEYWORD_RULES
    from backend.engines.categorize import apply_category_rules
    from backend.tests.helpers import rule as make_rule

    # Build rules from the keyword pack entries that target CAT_INTERNAL savings patterns
    rules = []
    for needle, field, cat_id, prio, notes in _KEYWORD_RULES:
        if cat_id != CAT_INTERNAL:
            continue
        if not any(
            x in needle.lower()
            for x in ("exchanged", "exchange to", "pocket", "vault", "to pocket")
        ):
            continue
        rules.append(
            make_rule(
                priority=prio,
                category_id=cat_id,
                match_field=field,
                match_type=MatchType.CONTAINS,
                match_value=needle,
                set_internal_transfer=True,
            )
        )
    assert rules, "expected savings-related internal keyword rules"

    exchanged = tx(description="Exchanged to CZK", amount="-9.30", currency="USD", merchant=None)
    out1 = apply_category_rules(exchanged, rules)
    assert out1.category_id == CAT_INTERNAL
    assert out1.is_internal_transfer is True

    pocket = tx(description="Pocket Withdrawal", amount="2986.86", currency="CZK")
    out2 = apply_category_rules(pocket, rules)
    assert out2.category_id == CAT_INTERNAL
    assert out2.is_internal_transfer is True

    # Real merchant purchase must not match these rules alone
    mol = tx(merchant="MOL", description="MOL", amount="-16.76", currency="USD")
    out3 = apply_category_rules(mol, rules)
    assert out3.category_id is None or out3.category_id != CAT_INTERNAL or not (
        "mol" in " ".join(r.match_value for r in rules).lower()
    )
    # With only savings rules, MOL should be unmatched
    assert out3.category_id is None


def test_manual_override_and_engine_batch():
    cat_food = category(
        name="Food",
        necessity=Necessity.VARIABLE_NECESSITY,
        life_domain=LifeDomain.FOOD,
    )
    cat_other = category(name="Other", life_domain=LifeDomain.OTHER)
    engine = CategoryEngine(
        rules=[
            rule(
                priority=10,
                category_id=cat_food.id,
                match_field=MatchField.DESCRIPTION,
                match_type=MatchType.CONTAINS,
                match_value="Barbecue",
            )
        ],
        categories=[cat_food, cat_other],
        fallback_category_id=cat_other.id,
    )
    t1 = tx(description="Bad Jeffs Barbecue", amount="-2500")
    t2 = tx(description="Mystery", amount="-50")
    t3 = CategoryEngine.apply_manual_override(
        tx(description="Spotify", amount="-185"),
        cat_food.id,
    )
    result = engine.categorize_many([t1, t2, t3])
    by_desc = {t.description: t for t in result.transactions}
    assert by_desc["Bad Jeffs Barbecue"].category_id == cat_food.id
    assert by_desc["Mystery"].category_id == cat_other.id  # fallback
    assert by_desc["Spotify"].category_override is True
    assert result.skipped_override == 1
