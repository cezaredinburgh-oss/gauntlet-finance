#!/usr/bin/env python3
"""
Ensure Fitness/Business categories, bootstrap keyword rules, rewire known
mis-maps, and reclassify non-override transactions.

Usage:
  python -m backend.scripts.reclassify_other_merchants --dry-run
  python -m backend.scripts.reclassify_other_merchants
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Match-value needles (case-insensitive contains) → preferred category id
_REWIRE_RULE_TARGETS: list[tuple[str, str]] = [
    ("alza", "shop_general"),
    ("shell", "moto_fuel"),
    ("omv", "moto_fuel"),
    ("mol", "moto_fuel"),
    ("benzina", "moto_fuel"),
    ("orlen", "moto_fuel"),
    ("eurooil", "moto_fuel"),
    ("tank ono", "moto_fuel"),
    ("artic bakehouse", "groceries"),
    ("bakehouse", "groceries"),
    ("openai", "software"),
    ("twitter", "software"),
    ("x.com", "software"),
    ("apple", "software"),
    ("active people", "fitness"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from backend.config import get_settings
    from backend.schema.default_categories import (
        CAT_BIZ_MATERIALS,
        CAT_FITNESS,
        CAT_GROCERIES,
        CAT_MOTO_FUEL,
        CAT_SHOP_GENERAL,
        CAT_SOFTWARE,
    )
    from backend.schema.models import CategoryRule
    from backend.services.categorization import (
        apply_rules_reclassify_non_override,
        bootstrap_rules_from_data,
        coverage_stats,
        ensure_default_categories,
    )
    from backend.services.response_cache import cache_invalidate
    from backend.sheets.google_sheets import (
        GoogleSheetsRepository,
        credentials_from_service_account,
    )

    cat_by_key = {
        "shop_general": CAT_SHOP_GENERAL,
        "moto_fuel": CAT_MOTO_FUEL,
        "groceries": CAT_GROCERIES,
        "software": CAT_SOFTWARE,
        "fitness": CAT_FITNESS,
        "biz_materials": CAT_BIZ_MATERIALS,
    }

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

    print("1) ensure_default_categories…")
    ens = ensure_default_categories(repo)
    print("   ", ens)

    if args.dry_run:
        print("[dry-run] would bootstrap rules + rewire + reclassify")
        cov = coverage_stats(repo, days=180)
        print(
            f"Coverage now {cov['coverage_pct']:.1f}% · "
            f"rules={cov['rules_count']} cats={cov['categories_count']}"
        )
        print("Top uncategorized:")
        for m in cov["top_uncategorized_merchants"][:15]:
            print(f"  {m['amount_usd']:>10}  {m['label'][:60]}")
        return 0

    print("2) bootstrap_rules_from_data…")
    boot = bootstrap_rules_from_data(repo, also_apply=False)
    print("   ", {k: boot[k] for k in boot if k != "apply"})

    print("3) rewire known rule targets…")
    rules = [
        r for r in repo.list_rows("CategoryRules") if isinstance(r, CategoryRule) and not r.archived
    ]
    rewired: list[CategoryRule] = []
    from backend.common.timeutil import utc_now

    now = utc_now()
    for r in rules:
        needle = (r.match_value or "").lower()
        for key, cat_key in _REWIRE_RULE_TARGETS:
            if key in needle:
                want = cat_by_key[cat_key]
                if r.category_id != want:
                    rewired.append(
                        r.model_copy(
                            update={
                                "category_id": want,
                                "is_active": True,
                                "notes": ((r.notes or "") + "; rewire:review_2026").strip("; "),
                                "updated_at": now,
                            }
                        )
                    )
                break
    if rewired:
        repo.upsert_rows("CategoryRules", rewired)
    print(f"   rewired={len(rewired)}")

    print("4) apply_rules_reclassify_non_override…")
    stats = apply_rules_reclassify_non_override(repo)
    print("   ", stats)

    try:
        cache_invalidate()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] cache_invalidate: {exc}")

    cov = coverage_stats(repo, days=180)
    print(
        f"Coverage {cov['coverage_pct']:.1f}% · "
        f"{cov['expense_usd_categorized']} / {cov['expense_usd_total']} · "
        f"rules={cov['rules_count']} cats={cov['categories_count']}"
    )
    print("Top uncategorized remaining:")
    for m in cov["top_uncategorized_merchants"][:15]:
        print(f"  {m['amount_usd']:>10}  {m['label'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
