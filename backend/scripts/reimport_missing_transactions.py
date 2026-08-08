#!/usr/bin/env python3
"""
Re-parse Bank statements/ cash CSVs and write only transactions that are
still missing from Google Sheets (after the dedupe fix).

Does not re-run investment FIFO (events/lots already complete).
Safe to run multiple times.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
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
    if not settings.spreadsheet_id:
        print("[FAIL] SPREADSHEET_ID not set")
        return 1

    creds = credentials_from_service_account(
        json_path=settings.google_application_credentials or None,
        json_inline=settings.google_service_account_json or None,
    )
    repo = GoogleSheetsRepository(
        settings.spreadsheet_id, creds, ensure_tabs=False
    )

    seed_minimal(repo)
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

    existing = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    print(f"Existing transactions in sheet: {len(existing)}")

    all_new: list[Transaction] = []
    for path in cash_files:
        if not path.is_file():
            print(f"[WARN] missing {path.name}")
            continue
        data = path.read_bytes()
        parsed = parse_statement_bytes(
            data,
            account_ids=acc_map,
            filename=path.name,
            now=utc_now(),
        )
        print(
            f"Parsed {path.name}: rows={parsed.row_count} "
            f"tx={len(parsed.transactions)}"
        )
        all_new.extend(parsed.transactions)

    deduped = StatementService.dedupe_transactions(existing, all_new)
    print(
        f"New after fixed dedupe: {len(deduped.transactions)} "
        f"(dropped as true dupes: {deduped.dropped_transactions})"
    )

    if not deduped.transactions:
        print("[OK] Nothing missing — sheet already complete for cash files.")
        return 0

    categories = [r for r in repo.list_rows("Categories") if isinstance(r, Category)]
    rules = [r for r in repo.list_rows("CategoryRules") if isinstance(r, CategoryRule)]
    cat_engine = CategoryEngine(rules=rules, categories=categories)
    categorized = cat_engine.categorize_many(deduped.transactions).transactions

    combined = existing + categorized
    matched = match_internal_transfers(combined)
    by_id = {t.id: t for t in matched.transactions}
    to_write = [by_id[t.id] for t in categorized]
    existing_updates = []
    for t in existing:
        m = by_id.get(t.id)
        if m and (
            m.is_internal_transfer != t.is_internal_transfer
            or m.transfer_group_id != t.transfer_group_id
        ):
            existing_updates.append(m)

    print(f"Writing {len(to_write)} new transactions…")
    repo.upsert_rows("Transactions", to_write)
    if existing_updates:
        print(f"Updating {len(existing_updates)} existing transfer flags…")
        repo.upsert_rows("Transactions", existing_updates)

    final = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    print(f"[OK] Sheet now has {len(final)} transactions "
          f"(was {len(existing)}, added ~{len(final) - len(existing)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
