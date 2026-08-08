#!/usr/bin/env python3
"""
Reclassify Revolut Digital Assets Europe pot moves as crypto funding + internal.

Cash legs of crypto buys (Transfer to …) and sell proceeds (Transfer from …)
must not count as living spend/income — InvestmentEvents already hold trades.

Usage (project root):
  python -m backend.scripts.repair_revolut_digital_assets_transfers --dry-run
  python -m backend.scripts.repair_revolut_digital_assets_transfers
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-overrides",
        action="store_true",
        help="Also rewrite rows with category_override=True",
    )
    args = parser.parse_args()

    from backend.config import get_settings
    from backend.schema.models import Transaction
    from backend.services.categorization import (
        is_revolut_digital_assets_transfer,
        repair_revolut_digital_assets_transfers,
    )
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

    if args.dry_run:
        txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction)]
        hits = [
            t
            for t in txs
            if not t.archived and is_revolut_digital_assets_transfer(t)
        ]
        need = [
            t
            for t in hits
            if not (
                str(t.category_id or "").endswith("000000000122")
                and t.is_internal_transfer
            )
            and not (t.category_override and not args.include_overrides)
        ]
        print(f"[dry-run] matched={len(hits)} would_update≈{len(need)}")
        for t in sorted(hits, key=lambda x: x.booking_date, reverse=True)[:20]:
            print(
                f"  {t.booking_date} {t.currency} {t.amount} "
                f"xfer={t.is_internal_transfer} cat={t.category_id} "
                f"{(t.description or '')[:60]}"
            )
        return 0

    stats = repair_revolut_digital_assets_transfers(
        repo,
        skip_user_overrides=not args.include_overrides,
    )
    try:
        cache_invalidate()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] cache_invalidate: {exc}")
    if hasattr(repo, "invalidate_cache"):
        try:
            repo.invalidate_cache()
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] repo.invalidate_cache: {exc}")

    print("OK:", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
