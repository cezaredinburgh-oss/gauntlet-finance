#!/usr/bin/env python3
"""
Repair Transactions tab after over-import:

1. Collapse true duplicates (same hard/soft identity) — keep oldest created_at.
2. Re-parse Bank statements cash files and add only truly missing rows.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from collections import defaultdict

    from backend.common.timeutil import utc_now
    from backend.config import get_settings
    from backend.engines.categorize import CategoryEngine
    from backend.engines.statements import StatementService
    from backend.engines.transfer_match import match_internal_transfers
    from backend.parsers import parse_statement_bytes
    from backend.schema.models import Account, Category, CategoryRule, Transaction
    from backend.scripts.seed_dev_repo import seed_minimal
    from backend.services.import_pipeline import _account_map
    from backend.sheets.google_sheets import (
        GoogleSheetsRepository,
        credentials_from_service_account,
    )

    get_settings.cache_clear()
    settings = get_settings()
    creds = credentials_from_service_account(
        json_path=settings.google_application_credentials or None,
        json_inline=settings.google_service_account_json or None,
    )
    repo = GoogleSheetsRepository(
        settings.spreadsheet_id, creds, ensure_tabs=False
    )

    seed_minimal(repo)
    existing = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    print(f"Before repair: {len(existing)} transactions")

    # --- Collapse duplicates ---
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in existing:
        key = StatementService._tx_hard_key(t) or StatementService._tx_soft_key(t)
        groups[key].append(t)

    keep: list[Transaction] = []
    removed = 0
    for key, rows in groups.items():
        rows_sorted = sorted(rows, key=lambda x: (x.created_at, str(x.id)))
        keep.append(rows_sorted[0])
        removed += len(rows_sorted) - 1

    print(f"Duplicate groups collapsed; removing {removed} extra rows")
    print(f"Unique after collapse: {len(keep)}")

    print(f"Rewriting Transactions tab with {len(keep)} unique rows…")
    repo.replace_all_rows("Transactions", keep)

    # --- Add missing from source files ---
    accounts = [a for a in repo.list_rows("Accounts") if isinstance(a, Account)]
    acc_map = _account_map(accounts)
    for ccy in (
        "CZK", "USD", "EUR", "GBP", "INR", "PLN", "CHF", "RON", "HUF",
        "SEK", "DKK", "NOK", "AUD", "CAD", "JPY", "SGD", "HKD",
    ):
        acc_map.setdefault(ccy, acc_map["default"])

    bank = _ROOT / "Bank statements"
    cash_files = [
        bank / "RB statemtn beginning to now.csv",
        bank / "revolut daily expenses all.csv",
    ]
    all_new: list[Transaction] = []
    for path in cash_files:
        if not path.is_file():
            continue
        parsed = parse_statement_bytes(
            path.read_bytes(),
            account_ids=acc_map,
            filename=path.name,
            now=utc_now(),
        )
        print(f"Parsed {path.name}: {len(parsed.transactions)} tx")
        all_new.extend(parsed.transactions)

    current = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    gap = StatementService.dedupe_transactions(current, all_new)
    print(
        f"Missing to add: {len(gap.transactions)} "
        f"(true dupes skipped: {gap.dropped_transactions})"
    )

    if gap.transactions:
        categories = [r for r in repo.list_rows("Categories") if isinstance(r, Category)]
        rules = [r for r in repo.list_rows("CategoryRules") if isinstance(r, CategoryRule)]
        cat = CategoryEngine(rules=rules, categories=categories)
        categorized = cat.categorize_many(gap.transactions).transactions
        combined = current + categorized
        matched = match_internal_transfers(combined)
        by_id = {t.id: t for t in matched.transactions}
        to_write = [by_id[t.id] for t in categorized]
        print(f"Writing {len(to_write)} missing transactions…")
        repo.upsert_rows("Transactions", to_write)

    final = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    # Expected ~14551 cash + nothing else if only those files
    print(f"[OK] Final transaction count: {len(final)}")
    print("Expected cash-only total ≈ 14551 (3002 RB + 11549 Revolut COMPLETED)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
