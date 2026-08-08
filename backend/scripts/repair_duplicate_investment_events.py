#!/usr/bin/env python3
"""
Collapse duplicate InvestmentEvents after overlapping statement imports.

Before the event soft-key fix, tax-year crypto/stocks re-exports could re-insert
the same trades because soft identity included ``original_file_hash``. This script
groups rows using the same soft∪hard key union as ``dedupe_events`` (connected
components via ``collapse_events_by_identity``) and keeps the earliest
``created_at`` (then lowest id).

**After a live repair you must rebuild lots:**

  python -m backend.scripts.rebuild_lots_from_events --dry-run
  python -m backend.scripts.rebuild_lots_from_events

LotAllocation rows are stripped from the keep set; rebuild recreates them via FIFO.

Usage (project root):
  python -m backend.scripts.repair_duplicate_investment_events --dry-run
  python -m backend.scripts.repair_duplicate_investment_events
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report duplicate groups without writing Sheets",
    )
    args = parser.parse_args()

    from backend.config import get_settings
    from backend.engines.statements import collapse_events_by_identity
    from backend.schema.models import InvestmentEvent, InvestmentEventType
    from backend.services.response_cache import cache_invalidate
    from backend.sheets.google_sheets import (
        GoogleSheetsRepository,
        credentials_from_service_account,
    )

    get_settings.cache_clear()
    settings = get_settings()
    if not settings.spreadsheet_id:
        print("ERROR: spreadsheet_id not configured")
        return 1

    creds = credentials_from_service_account(
        json_path=settings.google_application_credentials or None,
        json_inline=settings.google_service_account_json or None,
    )
    repo = GoogleSheetsRepository(
        settings.spreadsheet_id, creds, ensure_tabs=False
    )

    existing = [
        r
        for r in repo.list_rows("InvestmentEvents")
        if isinstance(r, InvestmentEvent) and not r.archived
    ]
    print(f"Loaded InvestmentEvents: {len(existing)}")

    # LotAllocation rows are rebuild artifacts — drop them; rebuild recreates.
    source_events = [
        e
        for e in existing
        if e.event_type != InvestmentEventType.LOT_ALLOCATION
    ]
    alloc_n = len(existing) - len(source_events)
    print(f"Source events (non-LotAllocation): {len(source_events)}")
    print(f"LotAllocation rows to drop: {alloc_n}")

    keep, removed = collapse_events_by_identity(source_events)
    print(f"Extra source rows to remove: {removed}")
    print(f"Unique source events to keep: {len(keep)}")
    print(
        "Identity: soft∪hard connected components (same as dedupe_events). "
        "Mixed legacy soft-only + new external_id rows collapse together."
    )
    print(
        "Note: follow with rebuild_lots_from_events so lots/FIFO match the "
        "collapsed event set."
    )

    if args.dry_run:
        print("[dry-run] No Sheets writes.")
        return 0

    print(
        f"Rewriting InvestmentEvents with {len(keep)} unique source events "
        f"(LotAllocations cleared)…"
    )
    repo.replace_all_rows("InvestmentEvents", keep)
    cache_invalidate()
    if hasattr(repo, "invalidate_cache"):
        try:
            repo.invalidate_cache()
        except Exception:  # noqa: BLE001
            pass

    print("[OK] InvestmentEvents collapsed.")
    print("Next: python -m backend.scripts.rebuild_lots_from_events --dry-run")
    print("Then: python -m backend.scripts.rebuild_lots_from_events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
