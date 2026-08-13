#!/usr/bin/env python3
"""
Rebuild InvestmentLots purely from InvestmentEvents already in Google Sheets.

Use after lot-engine fixes (e.g. reverse stock splits) so open inventory matches
statement history without re-uploading Bank statements.

**Critical:** previous runs upserted new LotAllocation rows without removing old
ones, which double-counted realized lifetime. This script always:

1. Strips all LotAllocation events before FIFO
2. Replaces InvestmentLots entirely
3. Replaces InvestmentEvents with non-allocations + fresh allocations only

Optional residual close for broker-verified zero positions (e.g. ENJ).

Usage (project root):
  python -m backend.scripts.rebuild_lots_from_events --dry-run
  python -m backend.scripts.rebuild_lots_from_events
  python -m backend.scripts.rebuild_lots_from_events --tickers PLTR,SPCX,COIN --dry-run
  python -m backend.scripts.rebuild_lots_from_events --collapse-dupes --dry-run
  python -m backend.scripts.rebuild_lots_from_events --close-residuals ENJ

After overlapping statement imports that left wrong open inventory, prefer:
  1) --collapse-dupes --dry-run  then without --dry-run
  2) this rebuild (always) so lots match Buy−Sell event net
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _close_residuals(lots: list, tickers: set[str]) -> list:
    from backend.common.timeutil import utc_now
    from backend.schema.models import LotStatus

    ts = utc_now()
    out = []
    closed_n = 0
    for lot in lots:
        if (
            lot.ticker.upper() in tickers
            and lot.status == LotStatus.OPEN
            and lot.quantity_remaining > 0
            and not lot.archived
        ):
            note = (lot.notes or "").strip()
            tag = "closed_residual_broker_zero"
            notes = f"{note}; {tag}".strip("; ") if note else tag
            out.append(
                lot.model_copy(
                    update={
                        "quantity_remaining": Decimal("0"),
                        "cost_basis_native": Decimal("0"),
                        "cost_basis_czk": Decimal("0"),
                        "cost_basis_usd": Decimal("0"),
                        "status": LotStatus.CLOSED,
                        "notes": notes,
                        "updated_at": ts,
                    }
                )
            )
            closed_n += 1
            print(
                f"  residual close {lot.ticker}: was rem={lot.quantity_remaining} "
                f"cost_usd={lot.cost_basis_usd}"
            )
        else:
            out.append(lot)
    print(f"Residual closes applied: {closed_n}")
    return out


def _realized_and_ratio(events: list) -> tuple[Decimal, dict[str, float]]:
    from backend.schema.models import InvestmentEventType
    from backend.services.realized import sum_realized_usd

    sell_q: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    alloc_q: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for e in events:
        if e.archived:
            continue
        tk = (e.ticker or "?").upper()
        if e.event_type == InvestmentEventType.SELL:
            sell_q[tk] += e.quantity or Decimal("0")
        elif e.event_type == InvestmentEventType.LOT_ALLOCATION:
            alloc_q[tk] += e.quantity or Decimal("0")
    ratios: dict[str, float] = {}
    for tk in sorted(set(sell_q) | set(alloc_q)):
        s = sell_q[tk]
        a = alloc_q[tk]
        if s > 0:
            ratios[tk] = float(a / s)
    return sum_realized_usd(events), ratios


def _renet_revolut_crypto_buys(events: list) -> tuple[list, int]:
    """
    One-shot: existing Revolut crypto Buy rows stored gross statement qty.
    Re-apply fee netting using value_native / fees_native already on the event.
    Idempotent via notes tag revolut_buy_fee_net.
    """
    from backend.parsers.revolut_crypto import (
        REVOLUT_BUY_FEE_NET_TAG,
        net_revolut_crypto_buy_quantity,
    )
    from backend.schema.models import (
        AssetClass,
        InvestmentEventType,
    )

    out = []
    n = 0
    for e in events:
        is_rev_crypto_buy = (
            e.event_type == InvestmentEventType.BUY
            and (e.source or "").strip().lower() == "revolut"
            and e.asset_class == AssetClass.CRYPTO
            and e.quantity is not None
            and e.quantity > 0
        )
        if not is_rev_crypto_buy:
            out.append(e)
            continue
        notes = e.notes or ""
        if REVOLUT_BUY_FEE_NET_TAG in notes:
            out.append(e)
            continue
        gross = e.quantity
        net, rate = net_revolut_crypto_buy_quantity(
            gross, e.value_native, e.fees_native
        )
        if rate is not None and rate > 0 and net != gross:
            tag = f"{REVOLUT_BUY_FEE_NET_TAG}; gross_qty={gross}; fee_rate={rate}"
            new_notes = f"{notes}; {tag}".strip("; ") if notes else tag
            out.append(
                e.model_copy(update={"quantity": net, "notes": new_notes, "lot_id": None})
            )
            n += 1
        else:
            tag = f"{REVOLUT_BUY_FEE_NET_TAG}; gross_qty={gross}"
            new_notes = f"{notes}; {tag}".strip("; ") if notes else tag
            out.append(e.model_copy(update={"notes": new_notes, "lot_id": None}))
    return out, n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--collapse-dupes",
        action="store_true",
        help="Collapse duplicate source events (soft∪hard identity) before FIFO",
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Optional comma-separated tickers to highlight in the open-qty report "
        "(rebuild is always full-ledger for consistency)",
    )
    parser.add_argument(
        "--close-residuals",
        default="",
        help="Comma-separated tickers to force-close residual open qty "
        "(default: none; e.g. ENJ)",
    )
    args = parser.parse_args()

    residual_tickers = {
        t.strip().upper() for t in args.close_residuals.split(",") if t.strip()
    }
    focus_tickers = {
        t.strip().upper() for t in args.tickers.split(",") if t.strip()
    } or {"PLTR", "SPCX", "COIN", "ETH", "DOGE", "XRP", "SOL", "ADA"}

    from backend.config import get_settings
    from backend.engines.lots import LotEngine
    from backend.engines.statements import collapse_events_by_identity
    from backend.schema.models import (
        InvestmentEvent,
        InvestmentEventType,
        LotStatus,
    )
    from backend.services.fx_amounts import build_fx_service
    from backend.services.lot_costs import enrich_lots
    from backend.services.lot_rebuild import event_net_by_ticker, open_qty_by_ticker
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

    events = [
        r for r in repo.list_rows("InvestmentEvents") if isinstance(r, InvestmentEvent)
    ]
    old_lots = list(repo.list_rows("InvestmentLots"))
    old_open = open_qty_by_ticker(
        [l for l in old_lots if hasattr(l, "ticker")]  # type: ignore[list-item]
    )
    old_realized, old_ratios = _realized_and_ratio(events)
    print(f"BEFORE: events={len(events)} realized_usd(deduped)={old_realized:.2f}")
    bad = {t: r for t, r in old_ratios.items() if abs(r - 1.0) > 0.02}
    if bad:
        print(f"BEFORE: alloc/sell qty ratios off (sample): {dict(list(bad.items())[:8])}")

    non_alloc = [e for e in events if e.event_type != InvestmentEventType.LOT_ALLOCATION]
    if args.collapse_dupes:
        non_alloc, removed = collapse_events_by_identity(non_alloc)
        print(f"Collapsed duplicate source events: removed {removed}, keep {len(non_alloc)}")
    # Clear lot links so FIFO opens lots purely from buy events
    cleaned = [e.model_copy(update={"lot_id": None}) for e in non_alloc]
    cleaned, renet_n = _renet_revolut_crypto_buys(cleaned)
    if renet_n:
        print(f"Re-netted Revolut crypto buys (gross→fee-net qty): {renet_n}")
    old_alloc_n = sum(1 for e in events if e.event_type == InvestmentEventType.LOT_ALLOCATION)
    print(f"FIFO inputs: non_alloc={len(cleaned)} dropping_old_allocs={old_alloc_n}")

    ev_net = event_net_by_ticker(cleaned)
    print("BEFORE open lots vs event net (focus tickers):")
    for t in sorted(focus_tickers):
        o = old_open.get(t, Decimal("0"))
        n = ev_net.get(t, Decimal("0"))
        flag = "  ** MISMATCH **" if o != n else ""
        print(f"  {t}: open_lots={o}  event_net(buy-sell)={n}{flag}")

    fx = build_fx_service(repo)
    engine = LotEngine(
        exemption_days=settings.holding_period_exemption_days,
        fx=fx,
    )
    fifo = engine.apply_events([], cleaned)
    rebuilt = enrich_lots(
        fifo.lots,
        fx,
        repo=repo,
        persist=False,
        fetch_missing_rates=True,
    )

    if residual_tickers:
        print(f"Closing residuals for: {sorted(residual_tickers)}")
        rebuilt = _close_residuals(rebuilt, residual_tickers)

    # Fresh event set: non-allocations (with updated lot_id links from FIFO) + new allocs
    # fifo.events contains cleaned events with links + new LotAllocations
    new_events = list(fifo.events)
    new_realized, new_ratios = _realized_and_ratio(new_events)
    new_alloc_n = sum(
        1 for e in new_events if e.event_type == InvestmentEventType.LOT_ALLOCATION
    )
    print(
        f"AFTER(rebuild): events={len(new_events)} allocs={new_alloc_n} "
        f"realized_usd={new_realized:.2f}"
    )
    bad_new = {t: r for t, r in new_ratios.items() if abs(r - 1.0) > 0.02}
    if bad_new:
        print(f"[WARN] alloc/sell ratios still off: {bad_new}")
    else:
        print("AFTER: all alloc/sell qty ratios ≈ 1.0")

    open_after = [
        l
        for l in rebuilt
        if l.status == LotStatus.OPEN and l.quantity_remaining > 0 and not l.archived
    ]
    by_ticker: dict[str, Decimal] = {}
    for l in open_after:
        by_ticker[l.ticker.upper()] = (
            by_ticker.get(l.ticker.upper(), Decimal("0")) + l.quantity_remaining
        )
    print(f"Rebuilt lots={len(rebuilt)} open={len(open_after)}")
    print("AFTER open lots (focus):")
    for t in sorted(focus_tickers):
        print(f"  open {t}: {by_ticker.get(t, 0)}  (was {old_open.get(t, 0)})")

    if args.dry_run:
        print("[dry-run] no write")
        return 0

    # Full replace — never upsert allocations on top of old ones
    repo.replace_all_rows("InvestmentLots", rebuilt)
    repo.replace_all_rows("InvestmentEvents", new_events)

    try:
        cache_invalidate()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] cache_invalidate: {exc}")
    if hasattr(repo, "invalidate_cache"):
        try:
            repo.invalidate_cache()
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] repo.invalidate_cache: {exc}")

    print(
        f"OK: lots+events replaced; realized {old_realized:.2f} → {new_realized:.2f} "
        f"(raw alloc rows {old_alloc_n} → {new_alloc_n})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
