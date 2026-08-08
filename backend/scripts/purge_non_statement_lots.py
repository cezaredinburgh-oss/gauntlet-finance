#!/usr/bin/env python3
"""
Purge open InvestmentLots that did not come from Bank statements imports.

Hard rule: holdings inventory must derive only from files under
  <project>/Bank statements/
Never from portfolio_desk, other iCloud folders, or manual desk ledgers.

This script:
1. Drops every lot tagged rebuilt_from_portfolio_desk_ledger (or notes containing 'desk')
2. Rebuilds lots via FIFO from InvestmentEvents already in the sheet
   (those events are only written by statement imports)
3. Replaces the InvestmentLots tab with closed+open lots from that rebuild

Usage (project root):
  python -m backend.scripts.purge_non_statement_lots
  python -m backend.scripts.purge_non_statement_lots --dry-run
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BANK_STATEMENTS = _ROOT / "Bank statements"


def _is_desk_lot(notes: str | None) -> bool:
    n = (notes or "").lower()
    return "desk" in n or "portfolio_desk" in n or "rebuilt_from_portfolio" in n


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not BANK_STATEMENTS.is_dir():
        print(f"[FAIL] Bank statements folder missing: {BANK_STATEMENTS}")
        return 1

    from backend.config import get_settings
    from backend.engines.lots import LotEngine
    from backend.schema.models import InvestmentEvent, InvestmentLot, LotStatus
    from backend.services.fx_amounts import build_fx_service
    from backend.services.lot_costs import enrich_lots
    from backend.services.portfolio_snapshot import portfolio_snapshot
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

    lots = [r for r in repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)]
    events = [
        r for r in repo.list_rows("InvestmentEvents") if isinstance(r, InvestmentEvent)
    ]

    desk_lots = [l for l in lots if _is_desk_lot(l.notes)]
    other_lots = [l for l in lots if not _is_desk_lot(l.notes)]
    open_before = sum(
        1 for l in lots if l.status == LotStatus.OPEN and l.quantity_remaining > 0
    )

    print(f"Bank statements dir: {BANK_STATEMENTS}")
    print(f"Lots total={len(lots)} desk_tagged={len(desk_lots)} other={len(other_lots)}")
    print(f"Open (qty>0) before={open_before}")
    print(f"InvestmentEvents={len(events)} (must already be from statement imports)")

    # Rebuild inventory purely from statement events (exclude allocation children)
    events_for_fifo = [
        e
        for e in events
        if e.event_type.value != "LotAllocation"
    ]
    # Clear pre-linked lot_ids on buys so engine opens fresh lots from events
    # Drop lot links so FIFO opens/closes purely from events (no desk lot ids)
    cleaned = [
        e.model_copy(update={"lot_id": None, "parent_event_id": e.parent_event_id})
        for e in events_for_fifo
    ]

    fx = build_fx_service(repo)
    engine = LotEngine(
        exemption_days=settings.holding_period_exemption_days,
        fx=fx,
    )
    # Start from ZERO lots — no desk inventory, no prior open lots
    fifo = engine.apply_events([], cleaned)
    rebuilt = enrich_lots(
        fifo.lots,
        fx,
        repo=repo,
        persist=False,
        fetch_missing_rates=True,
    )

    open_after = [
        l for l in rebuilt if l.status == LotStatus.OPEN and l.quantity_remaining > 0
    ]
    closed_after = [l for l in rebuilt if l.status != LotStatus.OPEN]
    cost = sum((l.cost_basis_usd or Decimal("0") for l in open_after), Decimal("0"))

    print(f"Rebuilt lots total={len(rebuilt)} open={len(open_after)} closed={len(closed_after)}")
    print(f"Open cost basis USD=${cost:,.2f}")
    print(f"Open tickers: {sorted({l.ticker for l in open_after})}")

    if args.dry_run:
        print("[dry-run] no write")
        return 0

    # Replace entire lots tab with statement-derived lots only
    repo.replace_all_rows("InvestmentLots", rebuilt)
    # Persist events that may have new lot_id / allocation links from FIFO
    if fifo.events:
        # Only upsert events that are allocations or updated links — full set is safer
        # for consistency after rebuild
        repo.upsert_rows("InvestmentEvents", fifo.events)

    snap = portfolio_snapshot(
        repo, exemption_days=settings.holding_period_exemption_days
    )
    print("=== After purge snapshot (statement-only lots) ===")
    print("cost", snap["total_cost_basis_usd"])
    print("mv", snap["total_market_value_usd"])
    print("unrealized", snap["unrealized_usd"])
    print(
        "tax available",
        snap["tax_runway"]["available_usd"],
        "locked",
        snap["tax_runway"]["locked_usd"],
    )
    print("OK: desk lots purged; inventory rebuilt from Bank statement events only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
