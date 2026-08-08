"""CLI: fetch CNB FX rates for a date range into FXRates sheet.

Usage (project root):
  $env:PYTHONPATH = "."
  python -m backend.scripts.fetch_cnb_fx_range --from 2026-01-01 --to 2026-01-31
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fetch CNB rates into FXRates")
    p.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    args = p.parse_args(argv)

    from backend.config import get_settings
    from backend.services.maintenance import fetch_cnb_range
    from backend.sheets.google_sheets import (
        GoogleSheetsRepository,
        credentials_from_service_account,
    )

    d0 = date.fromisoformat(args.date_from)
    d1 = date.fromisoformat(args.date_to)
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
    result = fetch_cnb_range(repo, date_from=d0, date_to=d1)
    print(result)
    return 0 if result.get("error_count", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
