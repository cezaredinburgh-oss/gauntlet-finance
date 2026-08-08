"""Statement extras for Investments: living draw, fees, staking.

Desk-parity aggregates over InvestmentEvents (not bank Transactions).

Revolut crypto fee-net (DOGE/XRP etc.)
--------------------------------------
Statement Buy *quantity* is gross; open lots store *net* units:

    qty_net = qty_gross * (1 - fees / value)

That adjustment is applied at parse time and affects holdings / MV only.

These extras are *cash-side*:

- Living draw uses Buy/Sell ``value_usd`` (fiat trade notional), not units.
  Fee-net quantity does not change sold/reinvested cash.
- Trade fees use ``fees_usd`` on Buy/Sell — this is where Revolut Metal ~0.99%
  service fees appear (the same fee column used for fee-net).
- Lot cost basis already capitalizes value + fees on open; fee totals still
  report cash paid as fees for transparency.

Staking rewards are zero-cost inventory and must not inflate living-draw
"reinvested".
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from backend.schema.models import InvestmentEvent, InvestmentEventType

if TYPE_CHECKING:
    from backend.engines.fx import FXService


def _d(v: Decimal | None) -> Decimal:
    return v if v is not None else Decimal("0")


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def _abs_usd(v: Decimal | None) -> Decimal:
    if v is None:
        return Decimal("0")
    return abs(v)


def _cashflow_usd(
    e: InvestmentEvent,
    fx: "FXService | None" = None,
) -> Decimal:
    """
    USD notional for buy/sell cashflow bars.

    Parsers often leave value_usd empty for CZK (etc.) legs — only set when
    native is already USD. Fall back to value_native + FX so multi-year
    history is not invisible on the chart.
    """
    direct = _abs_usd(e.value_usd)
    if direct > 0:
        return direct

    native = e.value_native
    if native is None:
        return Decimal("0")
    amt = abs(native)
    if amt <= 0:
        return Decimal("0")

    ccy = (e.native_currency or "").upper()
    if ccy == "USD" or not ccy:
        return amt

    if fx is None:
        return Decimal("0")
    converted = fx.convert(amt, ccy, "USD", e.event_date)
    if converted is None:
        return Decimal("0")
    return abs(converted)


def _money_str(v: Decimal) -> str:
    return str(_q2(v))


def _platform(e: InvestmentEvent) -> str:
    p = (e.source or "").strip()
    return p if p else "—"


def compute_living_draw_12m(
    events: Iterable[InvestmentEvent],
    *,
    as_of: date | None = None,
    window_days: int = 365,
    top_n: int = 12,
) -> dict[str, Any]:
    """Rolling cash draw: sold proceeds − buy investeds over window_days.

    Only parent Buy/Sell events. Excludes LotAllocation, StakingReward, Fee, etc.
    Uses abs(value_usd); missing value_usd contributes 0.
    """
    end = as_of or date.today()
    start = end - timedelta(days=window_days)
    sold = Decimal("0")
    bought = Decimal("0")
    by_ticker: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"sold": Decimal("0"), "bought": Decimal("0")}
    )

    for e in events:
        if e.archived:
            continue
        if e.event_type == InvestmentEventType.SELL:
            if e.event_date < start or e.event_date > end:
                continue
            amt = _abs_usd(e.value_usd)
            if amt <= 0:
                continue
            sold += amt
            tk = (e.ticker or "—").upper()
            by_ticker[tk]["sold"] += amt
        elif e.event_type == InvestmentEventType.BUY:
            if e.event_date < start or e.event_date > end:
                continue
            amt = _abs_usd(e.value_usd)
            if amt <= 0:
                continue
            bought += amt
            tk = (e.ticker or "—").upper()
            by_ticker[tk]["bought"] += amt
        # StakingReward / LotAllocation / Fee / … intentionally ignored

    draw = sold - bought
    rows: list[dict[str, Any]] = []
    for tk, v in by_ticker.items():
        d = v["sold"] - v["bought"]
        rows.append(
            {
                "ticker": tk,
                "sold_usd": _money_str(v["sold"]),
                "bought_usd": _money_str(v["bought"]),
                "draw_usd": _money_str(d),
                "_abs_draw": abs(d),
            }
        )
    rows.sort(key=lambda r: r["_abs_draw"], reverse=True)
    by_out = [
        {k: r[k] for k in ("ticker", "sold_usd", "bought_usd", "draw_usd")}
        for r in rows[:top_n]
    ]

    return {
        "window_days": window_days,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "sold_usd": _money_str(sold),
        "bought_usd": _money_str(bought),
        "draw_usd": _money_str(draw),
        "by_ticker": by_out,
        "notes": (
            "Cash notional from Buy/Sell value_usd. Revolut crypto fee-net "
            "affects units only; service fees appear under fees.trade_fees_usd."
        ),
    }


def _fee_amount(e: InvestmentEvent) -> Decimal:
    """USD fee cash on an event. Prefer fees_usd; Fee events may store value only."""
    fees = _abs_usd(e.fees_usd)
    if fees > 0:
        return fees
    if e.event_type == InvestmentEventType.FEE:
        # Explicit fee row: sometimes only value_* populated
        v = _abs_usd(e.value_usd)
        if v > 0:
            return v
        return _abs_usd(e.fees_native)  # last resort if USD missing
    return Decimal("0")


def _fee_type_label(e: InvestmentEvent) -> str:
    if e.event_type == InvestmentEventType.BUY:
        return "Buy fees"
    if e.event_type == InvestmentEventType.SELL:
        return "Sell fees"
    if e.event_type == InvestmentEventType.FEE:
        # Optional light split from description (Desk has Custody/Commission/…)
        text = f"{e.description or ''} {e.original_description or ''}".lower()
        if "custody" in text:
            return "Custody fee"
        if "commission" in text:
            return "Commission"
        if "deposit" in text and "fx" in text:
            return "Deposit FX fee"
        if "fx" in text and "fee" in text:
            return "Deposit FX fee"
        if "overnight" in text or "spread" in text:
            return "Fee"
        return "Fee"
    return e.event_type.value


def compute_fee_summary(events: Iterable[InvestmentEvent]) -> dict[str, Any]:
    """Lifetime + deposit/withdrawal cashflow-style summary (full history).

    Includes Revolut Buy/Sell ``fees_usd`` (service fee used for fee-net units).
    """
    trade_fees = Decimal("0")
    explicit = Decimal("0")
    deposits = Decimal("0")
    withdrawals = Decimal("0")

    # label -> platform -> amount
    type_plat: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )
    # platform -> label -> amount
    plat_type: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )

    for e in events:
        if e.archived:
            continue
        plat = _platform(e)

        if e.event_type == InvestmentEventType.DEPOSIT:
            deposits += _abs_usd(e.value_usd)
            continue
        if e.event_type == InvestmentEventType.WITHDRAWAL:
            withdrawals += _abs_usd(e.value_usd)
            continue

        if e.event_type in (InvestmentEventType.BUY, InvestmentEventType.SELL):
            amt = _fee_amount(e)
            if amt <= 0:
                continue
            trade_fees += amt
            label = _fee_type_label(e)
            type_plat[label][plat] += amt
            plat_type[plat][label] += amt
        elif e.event_type == InvestmentEventType.FEE:
            amt = _fee_amount(e)
            if amt <= 0:
                continue
            explicit += amt
            label = _fee_type_label(e)
            type_plat[label][plat] += amt
            plat_type[plat][label] += amt

    fees_by_event_type: list[dict[str, Any]] = []
    for label, plats in type_plat.items():
        total = sum(plats.values(), Decimal("0"))
        if total <= 0:
            continue
        by_platform = [
            {"platform": p, "amount_usd": _money_str(a)}
            for p, a in sorted(plats.items(), key=lambda x: x[1], reverse=True)
            if a > 0
        ]
        fees_by_event_type.append(
            {
                "label": label,
                "amount_usd": _money_str(total),
                "by_platform": by_platform,
            }
        )
    fees_by_event_type.sort(
        key=lambda x: Decimal(x["amount_usd"]), reverse=True
    )

    fees_by_platform: list[dict[str, Any]] = []
    for plat, labels in plat_type.items():
        total = sum(labels.values(), Decimal("0"))
        if total <= 0:
            continue
        by_type = [
            {"label": lab, "amount_usd": _money_str(a)}
            for lab, a in sorted(labels.items(), key=lambda x: x[1], reverse=True)
            if a > 0
        ]
        fees_by_platform.append(
            {
                "platform": plat,
                "amount_usd": _money_str(total),
                "by_type": by_type,
            }
        )
    fees_by_platform.sort(key=lambda x: Decimal(x["amount_usd"]), reverse=True)

    total = trade_fees + explicit
    return {
        "trade_fees_usd": _money_str(trade_fees),
        "explicit_fee_events_usd": _money_str(explicit),
        "total_fees_usd": _money_str(total),
        "deposits_usd": _money_str(deposits),
        "withdrawals_usd": _money_str(withdrawals),
        "fees_by_event_type": fees_by_event_type,
        "fees_by_platform": fees_by_platform,
        "notes": (
            "Lifetime from InvestmentEvents. Buy fees include Revolut crypto "
            "service fees (same Fees column used to fee-net buy units)."
        ),
    }


def compute_staking_summary(
    events: Iterable[InvestmentEvent],
    prices: Mapping[str, Decimal] | None = None,
) -> dict[str, Any]:
    """Staking reward marks by asset (broker value_usd or live qty × price)."""
    prices = prices or {}
    # ticker -> accumulators
    acc: dict[str, dict[str, Any]] = {}
    total_mark = Decimal("0")
    broker_mark_total = Decimal("0")
    live_mark_total = Decimal("0")
    reward_rows = 0

    for e in events:
        if e.archived:
            continue
        if e.event_type != InvestmentEventType.STAKING_REWARD:
            continue
        ticker = (e.ticker or "").strip().upper()
        if not ticker:
            continue
        reward_rows += 1
        units = abs(_d(e.quantity))
        broker = _abs_usd(e.value_usd)
        live = Decimal("0")
        if broker > 0:
            mark = broker
            src = "broker"
            broker_mark_total += broker
        elif units > 0 and ticker in prices and prices[ticker] > 0:
            live = units * prices[ticker]
            mark = live
            src = "live"
            live_mark_total += live
        else:
            mark = Decimal("0")
            src = "unknown"
        total_mark += mark

        if ticker not in acc:
            acc[ticker] = {
                "units": Decimal("0"),
                "events": 0,
                "mark": Decimal("0"),
                "broker": Decimal("0"),
                "live": Decimal("0"),
                "srcs": set(),
                "platforms": set(),
                "first": e.event_date,
                "last": e.event_date,
            }
        a = acc[ticker]
        a["units"] += units
        a["events"] += 1
        a["mark"] += mark
        a["broker"] += broker
        a["live"] += live
        a["srcs"].add(src)
        a["platforms"].add(_platform(e))
        if e.event_date < a["first"]:
            a["first"] = e.event_date
        if e.event_date > a["last"]:
            a["last"] = e.event_date

    by_ticker: list[dict[str, Any]] = []
    for ticker, a in acc.items():
        srcs = a["srcs"]
        if srcs == {"broker"}:
            mark_source = "broker"
        elif srcs == {"live"}:
            mark_source = "live"
        elif "broker" in srcs and "live" in srcs:
            mark_source = "mixed"
        else:
            mark_source = "unknown" if a["mark"] <= 0 else "mixed"
        plats = sorted(p for p in a["platforms"] if p and p != "—")
        by_ticker.append(
            {
                "ticker": ticker,
                "events": a["events"],
                "units": str(a["units"]),
                "mark_usd": _money_str(a["mark"]),
                "broker_usd": _money_str(a["broker"]),
                "live_usd": _money_str(a["live"]),
                "mark_source": mark_source,
                "platforms": plats,
                "first": a["first"].isoformat(),
                "last": a["last"].isoformat(),
            }
        )
    by_ticker.sort(key=lambda x: Decimal(x["mark_usd"]), reverse=True)

    return {
        "reward_rows": reward_rows,
        "units_sum": str(
            sum((Decimal(x["units"]) for x in by_ticker), Decimal("0"))
        ),
        "mark_usd_total": _money_str(total_mark),
        "broker_mark_usd": _money_str(broker_mark_total),
        "live_mark_usd": _money_str(live_mark_total),
        "by_ticker": by_ticker,
        "notes": (
            "Added value is reward mark in USD, not a cash deposit. "
            "Lots stay zero cost basis. Does not affect living-draw reinvested."
        ),
    }


def compute_cashflow_monthly(
    events: Iterable[InvestmentEvent],
    *,
    as_of: date | None = None,
    months: int | None = None,
    fx: "FXService | None" = None,
    trim_leading_zeros: bool = True,
) -> list[dict[str, Any]]:
    """Monthly buy/sell cash notional for reinvestment timeline.

    ``months`` is an explicit inclusive lookback (tests use small values).
    When ``months`` is None (snapshot path), the window starts at the first
    Buy/Sell on or before ``as_of`` and is capped at 120 months so the UI
    can offer 6m / 12m / 24m / All client-side slices.

    Cash amounts use ``value_usd`` when set; otherwise ``value_native`` (USD)
    or FX conversion of ``value_native`` so CZK/etc. history is not invisible.
    """
    end = as_of or date.today()
    ev_list = list(events)

    auto_window = months is None
    if months is None:
        first: date | None = None
        for e in ev_list:
            if e.archived:
                continue
            if e.event_type not in (
                InvestmentEventType.BUY,
                InvestmentEventType.SELL,
            ):
                continue
            if e.event_date > end:
                continue
            if first is None or e.event_date < first:
                first = e.event_date
        if first is None:
            months = 24
        else:
            span = (end.year - first.year) * 12 + (end.month - first.month) + 1
            months = max(1, min(120, span))
    else:
        months = max(1, int(months))

    # Only auto (snapshot) series trims empty prefix; explicit months keep full pad.
    if not auto_window:
        trim_leading_zeros = False

    # Inclusive window: first day of month (end - months + 1)
    year = end.year
    month = end.month - (months - 1)
    while month <= 0:
        month += 12
        year -= 1
    start = date(year, month, 1)

    by_month: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"bought": Decimal("0"), "sold": Decimal("0")}
    )
    for e in ev_list:
        if e.archived:
            continue
        if e.event_date < start or e.event_date > end:
            continue
        key = f"{e.event_date.year:04d}-{e.event_date.month:02d}"
        if e.event_type == InvestmentEventType.BUY:
            amt = _cashflow_usd(e, fx)
            if amt > 0:
                by_month[key]["bought"] += amt
        elif e.event_type == InvestmentEventType.SELL:
            amt = _cashflow_usd(e, fx)
            if amt > 0:
                by_month[key]["sold"] += amt

    # Emit every month in range (including zeros) for stable charts
    out: list[dict[str, Any]] = []
    cum_inv = Decimal("0")
    cum_proc = Decimal("0")
    y, m = start.year, start.month
    while date(y, m, 1) <= date(end.year, end.month, 1):
        key = f"{y:04d}-{m:02d}"
        bought = by_month[key]["bought"]
        sold = by_month[key]["sold"]
        cum_inv += bought
        cum_proc += sold
        rate = None
        if sold > 0:
            rate = float((bought / sold) * 100)
        # Unbounded historical ratio (kept for API compat; UI should not plot it).
        # Spikes when buys >> sells and flattens the dual-axis chart.
        cum_rate = None
        if cum_proc > 0:
            cum_rate = float((cum_inv / cum_proc) * 100)
        # Chart-safe 0–100%: share of cumulative sell proceeds matched by buy cash.
        # min(buys, sells)/sells — never exceeds 100 even with large net new capital.
        coverage = None
        if cum_proc > 0:
            covered = cum_inv if cum_inv < cum_proc else cum_proc
            coverage = float((covered / cum_proc) * 100)
        out.append(
            {
                "month": key,
                "bought_usd": _money_str(bought),
                "sold_usd": _money_str(sold),
                "net_usd": _money_str(sold - bought),
                "reinvestment_rate_pct": rate,
                "cumulative_reinvestment_rate_pct": cum_rate,
                "proceeds_coverage_pct": coverage,
                "cumulative_invested_usd": _money_str(cum_inv),
                "cumulative_proceeds_usd": _money_str(cum_proc),
                "cumulative_net_capital_usd": _money_str(cum_inv - cum_proc),
            }
        )
        m += 1
        if m > 12:
            m = 1
            y += 1

    # Drop leading empty months so "All" starts at first real cashflow
    if trim_leading_zeros and out:
        i = 0
        while i < len(out) and out[i]["bought_usd"] == "0.00" and out[i]["sold_usd"] == "0.00":
            i += 1
        if i > 0 and i < len(out):
            out = out[i:]
            # Recompute running cum fields from the trimmed start
            cum_inv = Decimal("0")
            cum_proc = Decimal("0")
            rebuilt: list[dict[str, Any]] = []
            for row in out:
                b = Decimal(row["bought_usd"])
                s = Decimal(row["sold_usd"])
                cum_inv += b
                cum_proc += s
                rate = float((b / s) * 100) if s > 0 else None
                cum_rate = float((cum_inv / cum_proc) * 100) if cum_proc > 0 else None
                coverage = None
                if cum_proc > 0:
                    covered = cum_inv if cum_inv < cum_proc else cum_proc
                    coverage = float((covered / cum_proc) * 100)
                rebuilt.append(
                    {
                        **row,
                        "reinvestment_rate_pct": rate,
                        "cumulative_reinvestment_rate_pct": cum_rate,
                        "proceeds_coverage_pct": coverage,
                        "cumulative_invested_usd": _money_str(cum_inv),
                        "cumulative_proceeds_usd": _money_str(cum_proc),
                        "cumulative_net_capital_usd": _money_str(cum_inv - cum_proc),
                    }
                )
            out = rebuilt
        elif i == len(out):
            # All zeros — keep last month only for a stable empty chart
            out = out[-1:]

    return out


def compute_statement_extras(
    events: Iterable[InvestmentEvent],
    prices: Mapping[str, Decimal] | None = None,
    *,
    as_of: date | None = None,
    window_days: int = 365,
    fx: "FXService | None" = None,
) -> dict[str, Any]:
    """Bundle living draw + fees + staking for portfolio_snapshot."""
    ev_list = list(events)
    price_map: dict[str, Decimal] = {}
    if prices:
        for k, v in prices.items():
            if v is not None and v > 0:
                price_map[str(k).upper()] = v

    return {
        "living_draw_12m": compute_living_draw_12m(
            ev_list, as_of=as_of, window_days=window_days
        ),
        "fees": compute_fee_summary(ev_list),
        "staking": compute_staking_summary(ev_list, price_map),
        "cashflow_monthly": compute_cashflow_monthly(
            ev_list, as_of=as_of, fx=fx
        ),
    }
