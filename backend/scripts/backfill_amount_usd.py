"""CLI: persist missing Transaction amount_usd via CNB/FX.

Usage (project root):
  $env:PYTHONPATH = "."
  python -m backend.scripts.backfill_amount_usd
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from backend.config import get_settings
    from backend.services.maintenance import backfill_amount_usd
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
    result = backfill_amount_usd(repo)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
