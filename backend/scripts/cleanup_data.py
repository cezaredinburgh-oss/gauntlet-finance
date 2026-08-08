#!/usr/bin/env python3
"""
CLI for scoped ledger cleanup.

  python -m backend.scripts.cleanup_data --preview
  python -m backend.scripts.cleanup_data --scopes investments --confirm DELETE
  python -m backend.scripts.cleanup_data --scopes transactions,statement_files --confirm DELETE
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Scoped cleanup of Google Sheets data")
    parser.add_argument(
        "--scopes",
        type=str,
        default="",
        help="Comma-separated scope ids (e.g. transactions,investments)",
    )
    parser.add_argument(
        "--confirm",
        type=str,
        default="",
        help='Must be DELETE to actually run',
    )
    parser.add_argument("--preview", action="store_true", help="Print row counts only")
    args = parser.parse_args()

    from backend.config import get_settings
    from backend.services.cleanup import CONFIRM_TOKEN, preview_cleanup, run_cleanup
    from backend.sheets.google_sheets import (
        GoogleSheetsRepository,
        credentials_from_service_account,
    )

    get_settings.cache_clear()
    settings = get_settings()
    if not settings.spreadsheet_id:
        print("[FAIL] SPREADSHEET_ID not configured")
        return 1

    repo = GoogleSheetsRepository(
        settings.spreadsheet_id,
        credentials_from_service_account(
            json_path=settings.google_application_credentials or None,
            json_inline=settings.google_service_account_json or None,
        ),
        ensure_tabs=False,
    )

    if args.preview or not args.scopes:
        prev = preview_cleanup(repo)
        print(json.dumps(prev, indent=2, default=str))
        return 0

    if args.confirm != CONFIRM_TOKEN:
        print(f'[FAIL] refuse without --confirm {CONFIRM_TOKEN}')
        return 2

    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    result = run_cleanup(repo, scopes)
    if hasattr(repo, "invalidate_cache"):
        repo.invalidate_cache()
    print(json.dumps({
        "scopes_applied": result.scopes_applied,
        "tabs_cleared": result.tabs_cleared,
        "transactions_uncategorized": result.transactions_uncategorized,
        "message": result.message,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
