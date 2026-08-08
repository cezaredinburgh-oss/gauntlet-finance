"""
End-to-end check of domain services against real Bank statements/.

1. Internal-transfer matcher on Raiffeisen + Revolut expenses
2. Lot engine tax-eligibility for PLTR / ETH / ADA (etc.)
3. Category rules for Spotify, rent, loan, foodora, …
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from backend.engines.categorize import CategoryEngine
from backend.engines.lots import LotEngine
from backend.engines.transfer_match import TransferMatchConfig, match_internal_transfers
from backend.parsers import parse_statement_bytes
from backend.schema.models import (
    Category,
    CategoryRule,
    LifeDomain,
    MatchField,
    MatchType,
    Necessity,
)
from backend.tests.helpers import category, rule

ROOT = Path(__file__).resolve().parents[2]
BANK = ROOT / "Bank statements"
AS_OF = date(2026, 8, 5)
TS = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)

# Stable account IDs so matcher sees different accounts
ACC_RB = uuid4()
ACC_REV = uuid4()
ACC_REV_STK = uuid4()
ACC_REV_CRY = uuid4()
ACC_ETORO = uuid4()

ACCOUNTS_CASH = {
    "default": ACC_REV,
    "CZK": ACC_REV,
    "USD": ACC_REV,
    "EUR": ACC_REV,
    "GBP": ACC_REV,
    "INR": ACC_REV,
    "PLN": ACC_REV,
    "CHF": ACC_REV,
    "RON": ACC_REV,
    "HUF": ACC_REV,
    "SEK": ACC_REV,
    "DKK": ACC_REV,
    "NOK": ACC_REV,
    "AUD": ACC_REV,
    "CAD": ACC_REV,
    "JPY": ACC_REV,
    "SGD": ACC_REV,
    "HKD": ACC_REV,
    "TRY": ACC_REV,
    "AED": ACC_REV,
    "MXN": ACC_REV,
    "BRL": ACC_REV,
    "NZD": ACC_REV,
    "THB": ACC_REV,
    "ILS": ACC_REV,
    "ZAR": ACC_REV,
    "RUB": ACC_REV,
    "CNY": ACC_REV,
}


def _parse(path: Path, account_ids: dict[str, UUID]):
    data = path.read_bytes()
    return parse_statement_bytes(data, account_ids=account_ids, filename=path.name)


def _blob(tx) -> str:
    return " ".join(
        filter(
            None,
            [
                tx.merchant,
                tx.description,
                tx.original_description,
                tx.counterparty_name,
                tx.notes,
            ],
        )
    ).lower()


def section_transfers() -> dict:
    print("=" * 88)
    print("1) INTERNAL TRANSFER MATCHER — Raiffeisen + Revolut expenses")
    print("=" * 88)

    rb_path = BANK / "RB statemtn beginning to now.csv"
    rev_path = BANK / "revolut daily expenses all.csv"

    # Raiffeisen uses CZK account
    rb = _parse(rb_path, {"CZK": ACC_RB, "default": ACC_RB})
    # Revolut multi-currency → all map to ACC_REV for cash ledger matching
    rev = _parse(rev_path, ACCOUNTS_CASH)

    # Force account_ids (parser already set them)
    rb_txs = [
        t.model_copy(update={"account_id": ACC_RB}) for t in rb.transactions
    ]
    rev_txs = [
        t.model_copy(update={"account_id": ACC_REV}) for t in rev.transactions
    ]

    combined = rb_txs + rev_txs
    result = match_internal_transfers(
        combined,
        config=TransferMatchConfig(
            date_window_days=5,
            amount_abs_tolerance=Decimal("1.00"),
            amount_rel_tolerance=Decimal("0.005"),
            min_auto_score=70,
        ),
    )

    linked = [t for t in result.transactions if t.transfer_group_id is not None]
    by_group: dict[UUID, list] = defaultdict(list)
    for t in linked:
        by_group[t.transfer_group_id].append(t)

    # Classify pairs: cross-institution Revolut↔Raiffeisen
    cross = []
    same_inst = []
    for gid, legs in by_group.items():
        insts = {l.source_institution for l in legs}
        if "Revolut" in insts and "Raiffeisen" in insts:
            cross.append((gid, legs))
        else:
            same_inst.append((gid, legs))

    # Known-pattern legs on RB: "Sent from Revolut" / merchant Revolut
    rb_revolut_inbound = [
        t
        for t in rb_txs
        if t.amount > 0
        and (
            "revolut" in _blob(t)
            or (t.merchant or "").lower() == "revolut"
        )
    ]
    rb_to_revolut_out = [
        t
        for t in rb_txs
        if t.amount < 0
        and (
            "revolut" in _blob(t)
            or (t.merchant or "").lower() == "revolut"
        )
    ]

    # How many RB Revolut-ish inflows got linked?
    linked_ids = {t.id for t in linked}
    inbound_linked = sum(1 for t in rb_revolut_inbound if t.id in linked_ids)
    outbound_linked = sum(1 for t in rb_to_revolut_out if t.id in linked_ids)

    print(f"  Parsed: Raiffeisen tx={len(rb_txs)}, Revolut expenses tx={len(rev_txs)}")
    print(f"  Pairs linked (total): {result.pairs_linked}")
    print(f"  Cross-institution Revolut↔Raiffeisen pairs: {len(cross)}")
    print(f"  Other pairs (same institution): {len(same_inst)}")
    print(
        f"  RB legs mentioning Revolut (inflows): {len(rb_revolut_inbound)} "
        f"→ linked {inbound_linked}"
    )
    print(
        f"  RB legs mentioning Revolut (outflows): {len(rb_to_revolut_out)} "
        f"→ linked {outbound_linked}"
    )

    print("\n  Sample cross-institution pairs (up to 8):")
    for gid, legs in sorted(
        cross,
        key=lambda x: min(l.booking_date for l in x[1]),
        reverse=True,
    )[:8]:
        legs_s = sorted(legs, key=lambda l: l.amount)
        for l in legs_s:
            print(
                f"    {l.booking_date} {l.source_institution:10} "
                f"{l.amount:>12} {l.currency}  "
                f"{(_blob(l)[:55])!r}"
            )
        print(f"    group={gid}")
        print()

    # Precision spot-check: every cross pair should net ~0 and different accounts
    bad = 0
    for gid, legs in cross:
        if len(legs) != 2:
            bad += 1
            continue
        a, b = legs
        if a.account_id == b.account_id:
            bad += 1
        if a.currency != b.currency:
            bad += 1
        if a.amount * b.amount >= 0:
            bad += 1
        if abs(abs(a.amount) - abs(b.amount)) > Decimal("1.00"):
            # allow tiny fee gap
            if abs(abs(a.amount) - abs(b.amount)) / max(abs(a.amount), abs(b.amount)) > Decimal(
                "0.01"
            ):
                bad += 1

    print(f"  Cross-pair integrity failures: {bad}")
    # Sample quality: linked pairs should not include pure Spotify/card merchants
    polluted = 0
    for gid, legs in cross:
        for l in legs:
            m = (l.merchant or "").lower()
            if m in {"spotify", "foodora", "lime", "albert"} and "revolut" not in _blob(l):
                polluted += 1
    print(f"  Polluted merchant legs in cross pairs: {polluted}")

    ok = (
        len(cross) > 0
        and bad == 0
        and inbound_linked > 0
        and polluted == 0
        and outbound_linked >= 10
    )
    print(
        f"  RESULT: {'PASS' if ok else 'FAIL'} "
        f"(cross pairs, RB Revolut legs linked, no merchant pollution)"
    )
    return {
        "ok": ok,
        "pairs": result.pairs_linked,
        "cross": len(cross),
        "inbound_linked": inbound_linked,
        "inbound_total": len(rb_revolut_inbound),
    }


def section_lots() -> dict:
    print()
    print("=" * 88)
    print(f"2) LOT ENGINE — tax eligibility as of {AS_OF}")
    print("=" * 88)

    engine = LotEngine(exemption_days=1095)

    stocks = _parse(
        BANK / "Revolut stocks.csv",
        {"default": ACC_REV_STK, "USD": ACC_REV_STK},
    )
    crypto = _parse(
        BANK / "Revolut crypto.csv",
        {"default": ACC_REV_CRY, "USD": ACC_REV_CRY},
    )
    etoro = _parse(
        BANK / "etoro_activity_import.csv",
        {"default": ACC_ETORO, "USD": ACC_ETORO},
    )

    # Rebuild lots via engine from events (authoritative FIFO), not parser-open lots alone
    all_events = (
        list(stocks.investment_events)
        + list(crypto.investment_events)
        + list(etoro.investment_events)
    )
    # Drop parser-created LotAllocation if any; engine creates them
    seed_events = [
        e
        for e in all_events
        if e.event_type.value != "LotAllocation"
    ]
    # Clear lot_id on sells so FIFO applies; keep buy lot links cleared so engine opens fresh
    cleaned = []
    for e in seed_events:
        if e.event_type.value in {"Buy", "StakingReward"}:
            cleaned.append(e.model_copy(update={"lot_id": None}))
        else:
            cleaned.append(e.model_copy(update={"lot_id": None}))

    state = engine.apply_events([], cleaned)

    tickers_of_interest = ["PLTR", "ETH", "ADA", "SOL", "SPCX", "TSLA", "PATH"]
    open_tickers = sorted(
        {
            lot.ticker.upper()
            for lot in state.lots
            if lot.quantity_remaining > 0 and lot.status.value == "Open"
        }
    )

    print(f"  Events processed: {len(cleaned)}")
    print(f"  Lots after FIFO: {len(state.lots)} (open tickers: {len(open_tickers)})")
    print(f"  Allocations created: {state.allocations_created}")
    print()

    summaries = {}
    for t in tickers_of_interest:
        s = engine.summarize_ticker(state.lots, t, as_of=AS_OF)
        if s.total_quantity <= 0:
            print(f"  {t}: no open quantity")
            continue
        summaries[t] = s
        print(
            f"  {t}: qty={s.total_quantity}  "
            f"tax-free={s.quantity_tax_free}  "
            f"pending={s.quantity_pending}  "
            f"cost_native={s.cost_basis_native} {s.native_currency}"
        )
        # Group pending free-on dates (collapse dust; show top upcoming only)
        pending_dates: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
        for lot in s.lots:
            if not lot.qualifies_3y_exemption:
                pending_dates[lot.tax_free_on] += lot.quantity_remaining
        if pending_dates:
            print("    becomes tax-free (next dates, qty≥0.01 or top 6):")
            shown = 0
            for d in sorted(pending_dates):
                q = pending_dates[d]
                if q < Decimal("0.01") and shown >= 3:
                    continue
                days = (d - AS_OF).days
                print(f"      {q} on {d} (in {days} days)")
                shown += 1
                if shown >= 6:
                    rest = len(pending_dates) - shown
                    if rest > 0:
                        print(f"      … +{rest} later date buckets")
                    break
        elig_lots = [lot for lot in s.lots if lot.qualifies_3y_exemption]
        if elig_lots:
            print(
                f"    already eligible lots: {len(elig_lots)} "
                f"(oldest acq {min(l.acquisition_date for l in elig_lots)})"
            )

    # Must answer for PLTR at minimum (known holdings from earlier analysis)
    pltr_ok = "PLTR" in summaries and summaries["PLTR"].total_quantity > 0
    eth_ok = "ETH" in summaries  # may be fully sold — still "answer" with 0 or open
    # ADA from eToro staking
    ada_s = engine.summarize_ticker(state.lots, "ADA", as_of=AS_OF)
    print()
    print(
        f"  ADA total open: {ada_s.total_quantity} "
        f"(tax-free={ada_s.quantity_tax_free}, pending={ada_s.quantity_pending})"
    )
    summaries["ADA"] = ada_s

    ok = pltr_ok and ada_s.total_quantity > 0
    print(f"  RESULT: {'PASS' if ok else 'FAIL'} (PLTR open + ADA open from rewards)")
    return {"ok": ok, "summaries": summaries, "allocations": state.allocations_created}


def _cat(name: str, necessity: Necessity, domain: LifeDomain, **kwargs) -> Category:
    return Category(
        id=uuid4(),
        name=name,
        necessity=necessity,
        life_domain=domain,
        created_at=TS,
        updated_at=TS,
        **kwargs,
    )


def section_categories() -> dict:
    print()
    print("=" * 88)
    print("3) CATEGORY ENGINE — sensible defaults on real cash transactions")
    print("=" * 88)

    cat_spotify = _cat("Spotify", Necessity.DISCRETIONARY, LifeDomain.SUBSCRIPTIONS)
    cat_subs = _cat("Subscriptions", Necessity.DISCRETIONARY, LifeDomain.SUBSCRIPTIONS)
    cat_food_delivery = _cat(
        "Food delivery", Necessity.DISCRETIONARY, LifeDomain.FOOD
    )
    cat_groceries = _cat(
        "Groceries", Necessity.VARIABLE_NECESSITY, LifeDomain.FOOD
    )
    cat_transport = _cat(
        "Transport", Necessity.VARIABLE_NECESSITY, LifeDomain.TRANSPORT
    )
    cat_rent = _cat("Rent", Necessity.FIXED, LifeDomain.HOUSING)
    cat_utilities = _cat("Utilities", Necessity.FIXED, LifeDomain.HOUSING)
    cat_loan = _cat("Loan repayment", Necessity.FIXED, LifeDomain.DEBT)
    cat_insurance = _cat("Insurance", Necessity.FIXED, LifeDomain.HEALTH)
    cat_telecom = _cat("Telecom", Necessity.FIXED, LifeDomain.SUBSCRIPTIONS)
    cat_internal = _cat(
        "Internal transfer",
        Necessity.FIXED,
        LifeDomain.TRANSFERS,
        is_transfer=True,
    )
    cat_other = _cat("Other", Necessity.DISCRETIONARY, LifeDomain.OTHER)

    categories = [
        cat_spotify,
        cat_subs,
        cat_food_delivery,
        cat_groceries,
        cat_transport,
        cat_rent,
        cat_utilities,
        cat_loan,
        cat_insurance,
        cat_telecom,
        cat_internal,
        cat_other,
    ]

    rules = [
        rule(priority=5, category_id=cat_spotify.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="Spotify"),
        rule(priority=5, category_id=cat_spotify.id, match_field=MatchField.DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Spotify"),
        rule(priority=10, category_id=cat_food_delivery.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="foodora"),
        rule(priority=10, category_id=cat_food_delivery.id, match_field=MatchField.DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Foodora"),
        rule(priority=10, category_id=cat_food_delivery.id, match_field=MatchField.DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Uber Eats"),
        rule(priority=10, category_id=cat_food_delivery.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="Wolt"),
        rule(priority=15, category_id=cat_groceries.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="Albert"),
        rule(priority=15, category_id=cat_groceries.id, match_field=MatchField.DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Albert"),
        rule(priority=15, category_id=cat_groceries.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="Rohlik"),
        rule(priority=15, category_id=cat_groceries.id, match_field=MatchField.DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Lidl"),
        rule(priority=20, category_id=cat_transport.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="Bolt"),
        rule(priority=20, category_id=cat_transport.id, match_field=MatchField.DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Bolt"),
        rule(priority=20, category_id=cat_transport.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="Lime"),
        rule(priority=20, category_id=cat_transport.id, match_field=MatchField.DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Uber"),
        # Word-boundary so "Current" (Revolut product) does not match "rent"
        rule(priority=8, category_id=cat_rent.id, match_field=MatchField.DESCRIPTION, match_type=MatchType.REGEX, match_value=r"(?i)\brent\b"),
        rule(priority=8, category_id=cat_rent.id, match_field=MatchField.ORIGINAL_DESCRIPTION, match_type=MatchType.REGEX, match_value=r"(?i)\brent\b"),
        rule(priority=8, category_id=cat_rent.id, match_field=MatchField.DESCRIPTION, match_type=MatchType.CONTAINS, match_value="nájem"),
        rule(priority=12, category_id=cat_loan.id, match_field=MatchField.DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Loan interest"),
        rule(priority=12, category_id=cat_loan.id, match_field=MatchField.ORIGINAL_DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Credit instalment"),
        rule(priority=12, category_id=cat_loan.id, match_field=MatchField.DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Loan"),
        rule(priority=12, category_id=cat_loan.id, match_field=MatchField.ORIGINAL_DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Loan interest"),
        rule(priority=12, category_id=cat_loan.id, match_field=MatchField.ORIGINAL_DESCRIPTION, match_type=MatchType.CONTAINS, match_value="instalment"),
        rule(priority=18, category_id=cat_insurance.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="Allianz"),
        rule(priority=18, category_id=cat_telecom.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="Vodafone"),
        rule(priority=18, category_id=cat_utilities.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="energetika"),
        rule(priority=18, category_id=cat_utilities.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="plynárensk"),
        rule(priority=25, category_id=cat_internal.id, match_field=MatchField.ORIGINAL_DESCRIPTION, match_type=MatchType.CONTAINS, match_value="Sent from Revolut", set_internal_transfer=True, institution_scope="Raiffeisen"),
        rule(priority=25, category_id=cat_internal.id, match_field=MatchField.MERCHANT, match_type=MatchType.EXACT, match_value="Revolut", set_internal_transfer=True, institution_scope="Raiffeisen"),
        rule(priority=30, category_id=cat_subs.id, match_field=MatchField.MERCHANT, match_type=MatchType.CONTAINS, match_value="Steam"),
    ]

    rb = _parse(
        BANK / "RB statemtn beginning to now.csv",
        {"CZK": ACC_RB, "default": ACC_RB},
    )
    rev = _parse(BANK / "revolut daily expenses all.csv", ACCOUNTS_CASH)
    all_tx = list(rb.transactions) + list(rev.transactions)

    engine = CategoryEngine(
        rules=rules,
        categories=categories,
        fallback_category_id=cat_other.id,
    )
    result = engine.categorize_many(all_tx)

    id_to_name = {c.id: c.name for c in categories}
    counts = Counter(
        id_to_name.get(t.category_id, "?") for t in result.transactions if t.category_id
    )

    print(f"  Transactions categorized: {len(result.transactions)}")
    print(f"  Assigned (changed): {result.assigned}, fallback/other bucket via default")
    print("  Category histogram (top):")
    for name, n in counts.most_common(15):
        print(f"    {name:22} {n:>6}")

    # Targeted precision checks
    def count_label(pred, label_id: UUID) -> tuple[int, int]:
        hits = [t for t in result.transactions if pred(t)]
        good = sum(1 for t in hits if t.category_id == label_id)
        return good, len(hits)

    checks = {
        "Spotify": count_label(
            lambda t: "spotify" in _blob(t),
            cat_spotify.id,
        ),
        "foodora": count_label(
            lambda t: "foodora" in _blob(t),
            cat_food_delivery.id,
        ),
        "rent": count_label(
            lambda t: (
                t.amount < 0
                and (
                    re.search(r"\brent\b", _blob(t), re.I) is not None
                    or "nájem" in _blob(t)
                )
            ),
            cat_rent.id,
        ),
        "loan": count_label(
            lambda t: "loan" in _blob(t) or "instalment" in _blob(t) or "credit instalment" in _blob(t),
            cat_loan.id,
        ),
        "Bolt transport": count_label(
            lambda t: (t.merchant or "").lower() == "bolt"
            or (
                "bolt" in _blob(t)
                and "food" not in _blob(t)
            ),
            cat_transport.id,
        ),
        "Allianz insurance": count_label(
            lambda t: "allianz" in _blob(t),
            cat_insurance.id,
        ),
    }

    print("\n  Targeted assignment rates (matched / candidates):")
    all_targets_ok = True
    for label, (good, total) in checks.items():
        rate = (good / total * 100) if total else 0
        # Expect high precision on clear merchants
        threshold = 0.85 if label in {"Spotify", "foodora", "Allianz insurance"} else 0.5
        ok = total == 0 or (good / total) >= threshold
        if not ok:
            all_targets_ok = False
        print(
            f"    [{'PASS' if ok else 'FAIL'}] {label:20} {good}/{total} ({rate:.0f}%)"
        )

    print(f"  RESULT: {'PASS' if all_targets_ok else 'FAIL'}")
    return {"ok": all_targets_ok, "counts": dict(counts), "checks": checks}


def main() -> int:
    t = section_transfers()
    l = section_lots()
    c = section_categories()

    print()
    print("=" * 88)
    print("SUMMARY")
    print("=" * 88)
    print(f"  Transfer matcher: {'PASS' if t['ok'] else 'FAIL'} "
          f"(cross pairs={t['cross']}, RB Revolut inflows linked "
          f"{t['inbound_linked']}/{t['inbound_total']})")
    print(f"  Lot tax eligibility: {'PASS' if l['ok'] else 'FAIL'} "
          f"(allocations={l['allocations']})")
    print(f"  Categories: {'PASS' if c['ok'] else 'FAIL'}")

    ok = t["ok"] and l["ok"] and c["ok"]
    print()
    print("RESULT:", "ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
