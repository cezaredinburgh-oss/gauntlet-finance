#!/usr/bin/env python3
"""
Optional operator backfill: apply active merchant-field rules to leftover residuals.

Loads Categories, Transactions, and CategoryRules once. Matches in memory
(first-match-wins among merchant needles length >= 3). Description /
original_description / counterparty / source_institution rules are excluded
(overbroad leftover needles such as "Single payment" / "To CZK").

Does not loop apply_one_rule_fill_residuals (that is N tab reads).
Not a public route. Not onboarding. Not auto-run.

Usage:
  python -m backend.scripts.apply_merchant_rules_fill_residuals --dry-run
  python -m backend.scripts.apply_merchant_rules_fill_residuals --apply
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.common.timeutil import utc_now
from backend.engines.categorize import rule_matches
from backend.schema.models import Category, CategoryRule, MatchField, Transaction
from backend.services.categorization import (
    _category_implies_internal_transfer,
    _is_blank_or_other_category,
)

_MIN_MERCHANT_NEEDLE = 3


@dataclass
class MerchantRuleUpdate:
    rule_id: UUID
    match_value: str
    category_id: UUID
    updated: int


@dataclass
class MerchantFillPlan:
    dirty: list[Transaction]
    scanned: int
    matched: int
    updated: int
    skipped_override: int
    skipped_already: int
    by_rule: list[MerchantRuleUpdate]
    merchant_rule_count: int


def iter_merchant_rules(rules: Sequence[Any]) -> list[CategoryRule]:
    """Active non-archived merchant rules with stripped needle length >= 3.

    Sorted by (priority, str(id)) so first-match-wins is deterministic.
    """
    out: list[CategoryRule] = []
    for raw in rules:
        if not isinstance(raw, CategoryRule):
            continue
        if not raw.is_active or raw.archived:
            continue
        field = (
            raw.match_field.value
            if isinstance(raw.match_field, MatchField)
            else str(raw.match_field)
        )
        if field != MatchField.MERCHANT.value:
            continue
        needle = (raw.match_value or "").strip()
        if len(needle) < _MIN_MERCHANT_NEEDLE:
            continue
        if needle != (raw.match_value or ""):
            out.append(raw.model_copy(update={"match_value": needle}))
        else:
            out.append(raw)
    out.sort(key=lambda r: (r.priority, str(r.id)))
    return out


def plan_merchant_residual_fills(
    txs: Sequence[Transaction],
    cats: Mapping[UUID, Category],
    rules: Sequence[Any],
) -> MerchantFillPlan:
    """Single-pass first-match-wins residual fills. No I/O."""
    cat_map = dict(cats)
    merchant_rules: list[CategoryRule] = []
    needs_internal: dict[UUID, bool] = {}
    for rule in iter_merchant_rules(rules):
        target = cat_map.get(rule.category_id)
        if target is None or target.archived:
            continue
        merchant_rules.append(rule)
        needs_internal[rule.id] = bool(rule.set_internal_transfer) or (
            _category_implies_internal_transfer(target)
        )

    now = utc_now()
    dirty: list[Transaction] = []
    counts: dict[UUID, int] = {r.id: 0 for r in merchant_rules}
    scanned = 0
    matched = 0
    updated_n = 0
    skipped_override = 0
    skipped_already = 0

    for tx in txs:
        if not isinstance(tx, Transaction) or tx.archived:
            continue
        scanned += 1
        winner: CategoryRule | None = None
        for rule in merchant_rules:
            if rule_matches(tx, rule):
                winner = rule
                break
        if winner is None:
            continue
        matched += 1
        if tx.category_override:
            skipped_override += 1
            continue
        if not _is_blank_or_other_category(tx, cat_map):
            skipped_already += 1
            continue
        internal = needs_internal[winner.id]
        if tx.category_id == winner.category_id and (
            not internal or tx.is_internal_transfer
        ):
            skipped_already += 1
            continue
        updates: dict[str, Any] = {
            "category_id": winner.category_id,
            "updated_at": now,
        }
        if internal:
            updates["is_internal_transfer"] = True
        dirty.append(tx.model_copy(update=updates))
        counts[winner.id] += 1
        updated_n += 1

    by_rule = [
        MerchantRuleUpdate(
            rule_id=r.id,
            match_value=r.match_value,
            category_id=r.category_id,
            updated=counts[r.id],
        )
        for r in merchant_rules
    ]
    return MerchantFillPlan(
        dirty=dirty,
        scanned=scanned,
        matched=matched,
        updated=updated_n,
        skipped_override=skipped_override,
        skipped_already=skipped_already,
        by_rule=by_rule,
        merchant_rule_count=len(merchant_rules),
    )


def _print_plan(plan: MerchantFillPlan, *, dry_run: bool) -> None:
    verb = "would_update" if dry_run else "updated"
    print(
        f"merchant_rules={plan.merchant_rule_count} scanned={plan.scanned} "
        f"matched={plan.matched} {verb}={plan.updated} "
        f"skipped_override={plan.skipped_override} "
        f"skipped_already={plan.skipped_already}"
    )
    for item in plan.by_rule:
        if item.updated == 0:
            continue
        needle = item.match_value[:60]
        print(f"  {needle!r}  {item.rule_id}  {verb}={item.updated}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan fills in memory; do not upsert Transactions (default)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write one Transactions upsert (required to mutate)",
    )
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        print("[FAIL] pass only one of --dry-run or --apply")
        return 2
    dry_run = not args.apply

    from backend.config import get_settings
    from backend.services.response_cache import cache_invalidate
    from backend.sheets.google_sheets import (
        GoogleSheetsRepository,
        credentials_from_service_account,
    )

    get_settings.cache_clear()
    settings = get_settings()
    if not settings.spreadsheet_id:
        print("[FAIL] SPREADSHEET_ID not set")
        return 1

    repo = GoogleSheetsRepository(
        settings.spreadsheet_id,
        credentials_from_service_account(
            json_path=settings.google_application_credentials or None,
            json_inline=settings.google_service_account_json or None,
        ),
        ensure_tabs=False,
    )

    # One list_rows per tab — looping apply_one_rule_fill_residuals is N Sheets reads.
    cats_rows = repo.list_rows("Categories")
    tx_rows = repo.list_rows("Transactions")
    rule_rows = repo.list_rows("CategoryRules")
    cats = {c.id: c for c in cats_rows if isinstance(c, Category)}
    txs = [t for t in tx_rows if isinstance(t, Transaction)]
    plan = plan_merchant_residual_fills(txs, cats, rule_rows)
    _print_plan(plan, dry_run=dry_run)

    if dry_run:
        print("[dry-run] no writes (pass --apply to upsert)")
        return 0

    if not plan.dirty:
        print("nothing to write")
        return 0

    repo.upsert_rows("Transactions", plan.dirty)
    try:
        cache_invalidate()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] cache_invalidate: {exc}")
    print(f"[ok] upserted {len(plan.dirty)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
