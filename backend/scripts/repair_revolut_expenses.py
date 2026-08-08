#!/usr/bin/env python3
"""
Replace all Revolut *cash* transactions with a full re-parse of
`Bank statements/revolut daily expenses all.csv` using stable per-row external_ids.

Keeps Raiffeisen and any other institutions untouched. Investments unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from backend.common.timeutil import utc_now
    from backend.config import get_settings
    from backend.engines.categorize import CategoryEngine
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
    repo = GoogleSheetsRepository(
        settings.spreadsheet_id,
        credentials_from_service_account(
            json_path=settings.google_application_credentials or None,
            json_inline=settings.google_service_account_json or None,
        ),
        ensure_tabs=False,
    )
    seed_minimal(repo)

    path = _ROOT / "Bank statements" / "revolut daily expenses all.csv"
    if not path.is_file():
        print(f"[FAIL] missing {path}")
        return 1

    all_tx = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    keep = [t for t in all_tx if t.source_institution != "Revolut"]
    old_rev = len(all_tx) - len(keep)
    print(f"Sheet total {len(all_tx)}; keeping non-Revolut {len(keep)}; replacing Revolut {old_rev}")

    accounts = [a for a in repo.list_rows("Accounts") if isinstance(a, Account)]
    acc_map = _account_map(accounts)
    for ccy in (
        "CZK", "USD", "EUR", "GBP", "INR", "PLN", "CHF", "RON", "HUF",
        "SEK", "DKK", "NOK", "AUD", "CAD", "JPY", "SGD", "HKD",
    ):
        acc_map.setdefault(ccy, acc_map["default"])

    parsed = parse_statement_bytes(
        path.read_bytes(),
        account_ids=acc_map,
        filename=path.name,
        now=utc_now(),
    )
    print(
        f"Re-parsed Revolut expenses: rows={parsed.row_count} "
        f"tx={len(parsed.transactions)} (unique ext="
        f"{len({t.external_id for t in parsed.transactions})})"
    )

    categories = [r for r in repo.list_rows("Categories") if isinstance(r, Category)]
    rules = [r for r in repo.list_rows("CategoryRules") if isinstance(r, CategoryRule)]
    cat = CategoryEngine(rules=rules, categories=categories)
    rev_tx = cat.categorize_many(parsed.transactions).transactions

    combined = keep + rev_tx
    matched = match_internal_transfers(combined)
    by_id = {t.id: t for t in matched.transactions}
    final = [by_id[t.id] for t in keep + rev_tx]

    print(f"Writing {len(final)} transactions (Raiffeisen+others {len(keep)} + Revolut {len(rev_tx)})…")
    repo.replace_all_rows("Transactions", final)

    check = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    by_inst = {}
    for t in check:
        by_inst[t.source_institution] = by_inst.get(t.source_institution, 0) + 1
    print(f"[OK] Final count {len(check)} by institution: {by_inst}")
    print("Expected: Raiffeisen 3002, Revolut 11549 → total 14551")
    return 0 if by_inst.get("Revolut") == 11549 and by_inst.get("Raiffeisen") == 3002 else 1


if __name__ == "__main__":
    raise SystemExit(main())
