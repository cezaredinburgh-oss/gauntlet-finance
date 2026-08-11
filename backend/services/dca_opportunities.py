"""DCA opportunity alerts for existing open positions.

Uses statement lots + latest marks (and optional Yahoo 1y history for
pullback / 52-week average context). Fail-open when history is unavailable.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence

from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
    Price,
)

logger = logging.getLogger(__name__)

# --- Tunable thresholds (single place) ---
DCA_MIN_POSITION_USD = Decimal("400")
# Board shows more names than alerts (still drops pure dust).
DCA_BOARD_MIN_POSITION_USD = Decimal("100")
DCA_COOLDOWN_DAYS = 21
DCA_MAX_WEIGHT_PCT = 35.0
DCA_MAX_ALERTS = 3
DCA_STALE_PRICE_DAYS = 7

DCA_STOCK_COST_DISCOUNT_PCT = 10.0
DCA_CRYPTO_COST_DISCOUNT_PCT = 18.0
DCA_STOCK_PULLBACK_PCT = 12.0
DCA_CRYPTO_PULLBACK_PCT = 20.0
# Mark must sit this far *under* the 52-week average close (mean reversion).
DCA_STOCK_BELOW_52W_AVG_PCT = 5.0
DCA_CRYPTO_BELOW_52W_AVG_PCT = 10.0
# For pullback / 52w-avg signals: don't DCA into melt-ups far above book cost.
DCA_PULLBACK_MAX_PREMIUM_VS_COST_PCT = 5.0

DCA_WARN_STOCK_DISCOUNT_PCT = 25.0
DCA_WARN_CRYPTO_DISCOUNT_PCT = 35.0

HistoryStats = dict[str, Any]  # high_3m, avg_52w, high_52w (Decimal | None)
HistoryStatsFetcher = Callable[[list[str], dict[str, str | None]], dict[str, HistoryStats]]


@dataclass(frozen=True)
class PositionDcaRow:
    ticker: str
    asset_class: str  # "Crypto" | "Stock" | …
    qty: Decimal
    cost_usd: Decimal
    avg_cost: Decimal
    mark: Decimal
    price_as_of: date
    last_buy: date
    days_since_buy: int
    position_usd: Decimal
    weight_pct: float
    mv_usd: Decimal


@dataclass(frozen=True)
class DcaCandidate:
    ticker: str
    level: str  # info | warn
    score: float
    title: str
    body: str
    href: str
    discount_vs_cost_pct: float
    pullback_pct: float | None
    below_52w_avg_pct: float | None
    signal_a: bool
    signal_b: bool


def _d(v: Decimal | None) -> Decimal:
    return v if v is not None else Decimal("0")


def _is_crypto(asset_class: str | AssetClass | None) -> bool:
    if asset_class is None:
        return False
    raw = asset_class.value if isinstance(asset_class, AssetClass) else str(asset_class)
    return raw.strip().lower() == "crypto"


def _price_as_of_date(as_of: datetime | date) -> date:
    if isinstance(as_of, datetime):
        return as_of.date() if as_of.tzinfo is None else as_of.astimezone(timezone.utc).date()
    return as_of


def _is_staking_reward_lot(
    lot: InvestmentLot,
    *,
    staking_open_event_ids: set,
) -> bool:
    """True for lots opened by StakingReward (must not reset DCA 'days since buy')."""
    if lot.open_event_id is not None and lot.open_event_id in staking_open_event_ids:
        return True
    notes = (lot.notes or "").lower()
    if "staking reward" in notes or "staking_reward" in notes:
        return True
    return False


def last_buy_dates(
    lots: Sequence[InvestmentLot],
    events: Sequence[InvestmentEvent],
) -> dict[str, date]:
    """
    Latest **cash purchase** date per ticker for DCA cooldown / days-since-buy.

    Uses:
      1. ``InvestmentEventType.BUY`` event dates (preferred), and
      2. open-lot ``acquisition_date`` only for lots that are **not** staking rewards.

    StakingReward opens a new tax lot (correct for Czech 3y inventory) but is
    not a discretionary add — counting it was zeroing "Xd since buy" for every
    staked coin after a rewards export (BTC unaffected if it has no rewards).
    """
    staking_open_ids = {
        e.id
        for e in events
        if not e.archived and e.event_type == InvestmentEventType.STAKING_REWARD
    }

    event_last: dict[str, date] = {}
    for e in events:
        if e.archived or e.event_type != InvestmentEventType.BUY or not e.ticker:
            continue
        t = e.ticker.upper()
        prev = event_last.get(t)
        if prev is None or e.event_date > prev:
            event_last[t] = e.event_date

    lot_last: dict[str, date] = {}
    for lot in lots:
        if lot.archived or lot.status != LotStatus.OPEN or lot.quantity_remaining <= 0:
            continue
        if _is_staking_reward_lot(lot, staking_open_event_ids=staking_open_ids):
            continue
        t = lot.ticker.upper()
        prev = lot_last.get(t)
        if prev is None or lot.acquisition_date > prev:
            lot_last[t] = lot.acquisition_date

    merged: dict[str, date] = {}
    for t in set(lot_last) | set(event_last):
        dates = [d for d in (lot_last.get(t), event_last.get(t)) if d is not None]
        if dates:
            merged[t] = max(dates)
    return merged


def build_position_dca_rows(
    lots: Sequence[InvestmentLot],
    events: Sequence[InvestmentEvent],
    prices: Mapping[str, Price],
    *,
    as_of: date | None = None,
) -> list[PositionDcaRow]:
    """Aggregate open lots into per-ticker DCA inputs (no signal evaluation)."""
    as_of = as_of or date.today()
    buy_dates = last_buy_dates(lots, events)

    by_ticker: dict[str, list[InvestmentLot]] = {}
    for lot in lots:
        if lot.archived or lot.status != LotStatus.OPEN or lot.quantity_remaining <= 0:
            continue
        t = lot.ticker.upper()
        by_ticker.setdefault(t, []).append(lot)

    # First pass: MV/cost for weights
    raw: list[tuple[str, Decimal, Decimal, Decimal, str, date, date]] = []
    # ticker, qty, cost, mark, asset_class, price_as_of, last_buy
    book_value = Decimal("0")

    for ticker, t_lots in by_ticker.items():
        px = prices.get(ticker) or prices.get(ticker.upper())
        if px is None:
            continue
        mark = _d(px.price)
        if mark <= 0:
            continue
        px_day = _price_as_of_date(px.as_of)
        qty = sum((lot.quantity_remaining for lot in t_lots), Decimal("0"))
        cost = sum((_d(lot.cost_basis_usd) for lot in t_lots), Decimal("0"))
        if qty <= 0 or cost <= 0:
            continue
        ac = "Stock"
        for lot in t_lots:
            if lot.asset_class is not None:
                ac = lot.asset_class.value
                break
        last_buy = buy_dates.get(ticker) or max(lot.acquisition_date for lot in t_lots)
        mv = qty * mark
        book_value += mv
        raw.append((ticker, qty, cost, mark, ac, px_day, last_buy))

    if book_value <= 0:
        book_value = Decimal("1")

    rows: list[PositionDcaRow] = []
    for ticker, qty, cost, mark, ac, px_day, last_buy in raw:
        mv = qty * mark
        avg_cost = cost / qty
        position_usd = mv if mv > cost else cost
        weight = float(mv / book_value * 100) if book_value else 0.0
        rows.append(
            PositionDcaRow(
                ticker=ticker,
                asset_class=ac,
                qty=qty,
                cost_usd=cost,
                avg_cost=avg_cost,
                mark=mark,
                price_as_of=px_day,
                last_buy=last_buy,
                days_since_buy=(as_of - last_buy).days,
                position_usd=position_usd,
                weight_pct=weight,
                mv_usd=mv,
            )
        )
    return rows


def _cost_discount_threshold(is_crypto: bool) -> float:
    return DCA_CRYPTO_COST_DISCOUNT_PCT if is_crypto else DCA_STOCK_COST_DISCOUNT_PCT


def _pullback_threshold(is_crypto: bool) -> float:
    return DCA_CRYPTO_PULLBACK_PCT if is_crypto else DCA_STOCK_PULLBACK_PCT


def _below_52w_threshold(is_crypto: bool) -> float:
    return DCA_CRYPTO_BELOW_52W_AVG_PCT if is_crypto else DCA_STOCK_BELOW_52W_AVG_PCT


def _warn_discount_threshold(is_crypto: bool) -> float:
    return DCA_WARN_CRYPTO_DISCOUNT_PCT if is_crypto else DCA_WARN_STOCK_DISCOUNT_PCT


def _q2_str(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01")))


@dataclass(frozen=True)
class DcaMetrics:
    discount_vs_cost_pct: float
    premium_vs_cost_pct: float
    near_or_below_cost: bool
    pullback_pct: float | None
    below_52w_avg_pct: float | None
    signal_a: bool
    signal_b1: bool
    signal_b2: bool
    signal_b: bool
    score: float


def compute_dca_metrics(
    row: PositionDcaRow,
    *,
    high_3m: Decimal | None = None,
    avg_52w: Decimal | None = None,
) -> DcaMetrics:
    """Continuous metrics + signal flags (no hard gates)."""
    crypto = _is_crypto(row.asset_class)
    discount = float((row.avg_cost - row.mark) / row.avg_cost * 100) if row.avg_cost > 0 else 0.0
    premium = float((row.mark - row.avg_cost) / row.avg_cost * 100) if row.avg_cost > 0 else 0.0
    near = premium <= DCA_PULLBACK_MAX_PREMIUM_VS_COST_PCT

    pullback: float | None = None
    if high_3m is not None and high_3m > 0:
        pullback = float((high_3m - row.mark) / high_3m * 100)

    below_52w: float | None = None
    if avg_52w is not None and avg_52w > 0:
        below_52w = float((avg_52w - row.mark) / avg_52w * 100)

    signal_a = discount >= _cost_discount_threshold(crypto)
    signal_b1 = (
        pullback is not None
        and pullback >= _pullback_threshold(crypto)
        and near
    )
    signal_b2 = (
        below_52w is not None
        and below_52w >= _below_52w_threshold(crypto)
        and near
    )
    signal_b = signal_b1 or signal_b2
    score = (
        1.0 * max(discount, 0.0)
        + 0.6 * max(pullback or 0.0, 0.0)
        + 0.5 * max(below_52w or 0.0, 0.0)
        + 0.15 * float(min(row.days_since_buy, 120))
        + 0.05 * min(math.log10(float(row.position_usd) + 1.0), 5.0)
    )
    return DcaMetrics(
        discount_vs_cost_pct=discount,
        premium_vs_cost_pct=premium,
        near_or_below_cost=near,
        pullback_pct=pullback,
        below_52w_avg_pct=below_52w,
        signal_a=signal_a,
        signal_b1=signal_b1,
        signal_b2=signal_b2,
        signal_b=signal_b,
        score=score,
    )


def gate_blockers(row: PositionDcaRow, *, as_of: date | None = None) -> list[str]:
    """Hard-gate reasons that would suppress an alert (board still ranks)."""
    as_of = as_of or date.today()
    blockers: list[str] = []
    if row.mark <= 0 or row.avg_cost <= 0:
        blockers.append("unpriced")
    if row.position_usd < DCA_MIN_POSITION_USD:
        blockers.append("materiality")
    if row.days_since_buy < DCA_COOLDOWN_DAYS:
        blockers.append("cooldown")
    if row.weight_pct > DCA_MAX_WEIGHT_PCT:
        blockers.append("concentration")
    if (as_of - row.price_as_of).days > DCA_STALE_PRICE_DAYS:
        blockers.append("stale_price")
    return blockers


def evaluate_dca_opportunity(
    row: PositionDcaRow,
    *,
    as_of: date | None = None,
    high_3m: Decimal | None = None,
    avg_52w: Decimal | None = None,
) -> DcaCandidate | None:
    """
    Apply hard gates + Signal A (below avg cost) + Signal B (pullback / 52w avg).

    Signal B reasoning:
      - B1: meaningful pullback from recent (3M) high while not extended vs book cost
      - B2: mark is a clear drawdown *below the 52-week average close* (mean reversion
        on a name you already hold), again while not chasing far above avg cost
    """
    as_of = as_of or date.today()
    if gate_blockers(row, as_of=as_of):
        return None

    m = compute_dca_metrics(row, high_3m=high_3m, avg_52w=avg_52w)
    if not (m.signal_a or m.signal_b):
        return None

    crypto = _is_crypto(row.asset_class)
    level = "info"
    if m.discount_vs_cost_pct >= _warn_discount_threshold(crypto):
        level = "warn"

    parts: list[str] = []
    if m.signal_a or m.discount_vs_cost_pct > 0:
        parts.append(
            f"Mark is {m.discount_vs_cost_pct:.0f}% "
            f"{'below' if m.discount_vs_cost_pct >= 0 else 'above'} your average cost "
            f"(${row.mark:,.2f} vs ${row.avg_cost:,.2f}/unit)."
        )
    elif m.premium_vs_cost_pct > 0:
        parts.append(
            f"Mark ${row.mark:,.2f} is near your average cost "
            f"(${row.avg_cost:,.2f}/unit, +{m.premium_vs_cost_pct:.0f}%)."
        )
    parts.append(f"Last add {row.days_since_buy} days ago.")
    if m.signal_b1 and m.pullback_pct is not None:
        parts.append(f"3M pullback ~{m.pullback_pct:.0f}%.")
    if m.signal_b2 and m.below_52w_avg_pct is not None and avg_52w is not None:
        parts.append(
            f"Trading ~{m.below_52w_avg_pct:.0f}% below its 52-week average "
            f"(${avg_52w:,.2f})."
        )
    if not m.signal_a and m.signal_b:
        parts.append("Dip on an existing holding — consider a disciplined add.")

    return DcaCandidate(
        ticker=row.ticker,
        level=level,
        score=m.score,
        title=f"DCA opportunity: {row.ticker}",
        body=" ".join(parts),
        href="/investments/dca",
        discount_vs_cost_pct=m.discount_vs_cost_pct,
        pullback_pct=m.pullback_pct,
        below_52w_avg_pct=m.below_52w_avg_pct,
        signal_a=m.signal_a,
        signal_b=m.signal_b,
    )


def select_top_dca_candidates(
    candidates: Sequence[DcaCandidate],
    *,
    limit: int = DCA_MAX_ALERTS,
) -> list[DcaCandidate]:
    ranked = sorted(candidates, key=lambda c: (-c.score, c.ticker))
    return list(ranked[:limit])


def candidates_to_alerts(
    candidates: Sequence[DcaCandidate],
    *,
    total_eligible: int | None = None,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    shown = list(candidates)
    for i, c in enumerate(shown):
        body = c.body
        if i == 0 and total_eligible is not None and total_eligible > len(shown):
            extra = total_eligible - len(shown)
            body = f"{body} (+{extra} more holding{'s' if extra != 1 else ''} also qualify)."
        alerts.append(
            {
                "id": f"dca_opportunity_{c.ticker}",
                "level": c.level,
                "title": c.title,
                "body": body,
                "href": c.href,
            }
        )
    return alerts


def history_stats_from_closes(
    series: Sequence[tuple[str, Decimal]],
    *,
    as_of: date | None = None,
) -> HistoryStats:
    """
    From (iso_ts, close) points, compute 3M high and ~52-week average.

    Uses calendar windows on the timestamp date. Empty series → nulls.
    """
    as_of = as_of or date.today()
    if not series:
        return {"high_3m": None, "avg_52w": None, "high_52w": None}

    points: list[tuple[date, Decimal]] = []
    for ts, px in series:
        try:
            day = date.fromisoformat(str(ts)[:10])
        except ValueError:
            continue
        if px is None or px <= 0:
            continue
        points.append((day, px))
    if not points:
        return {"high_3m": None, "avg_52w": None, "high_52w": None}

    d3 = as_of - timedelta(days=93)
    d52 = as_of - timedelta(days=365)
    closes_3m = [px for day, px in points if day >= d3]
    closes_52 = [px for day, px in points if day >= d52]
    if not closes_52:
        closes_52 = [px for _, px in points]

    high_3m = max(closes_3m) if closes_3m else None
    high_52w = max(closes_52) if closes_52 else None
    if closes_52:
        avg_52w = sum(closes_52, Decimal("0")) / Decimal(len(closes_52))
    else:
        avg_52w = None
    return {"high_3m": high_3m, "avg_52w": avg_52w, "high_52w": high_52w}


def fetch_history_stats_yfinance(
    tickers: list[str],
    asset_classes: dict[str, str | None],
) -> dict[str, HistoryStats]:
    """Best-effort 1y daily history → per-ticker high_3m / avg_52w. Fail-open."""
    if not tickers:
        return {}
    try:
        from backend.services.price_history import (
            _HISTORY_CACHE,
            _yfinance_history_batch,
        )
        from backend.services.prices import _normalize_yahoo_symbol
        import time
    except Exception as exc:  # noqa: BLE001
        logger.warning("DCA history import failed: %s", exc)
        return {}

    yahoo_map: dict[str, str] = {}
    for t in tickers:
        ysym = _normalize_yahoo_symbol(t, asset_classes.get(t))
        yahoo_map[ysym] = t.upper()
    yahoo_symbols = list(yahoo_map.keys())
    cache_key = f"dca|1y|1d|{'|'.join(sorted(yahoo_symbols))}"
    now_m = time.monotonic()
    ttl = 3600.0
    if cache_key in _HISTORY_CACHE:
        fetched, payload = _HISTORY_CACHE[cache_key]
        if now_m - fetched <= ttl:
            closes = payload
        else:
            closes = None
    else:
        closes = None

    if closes is None:
        try:
            closes = _yfinance_history_batch(yahoo_symbols, yahoo_map, "1y", "1d")
            _HISTORY_CACHE[cache_key] = (time.monotonic(), closes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DCA yfinance history failed: %s", exc)
            return {}

    out: dict[str, HistoryStats] = {}
    for t in tickers:
        series = closes.get(t.upper(), []) if closes else []
        out[t.upper()] = history_stats_from_closes(series)
    return out


def _normalize_stats(
    stats_by_ticker: dict[str, HistoryStats],
    ticker: str,
) -> tuple[Decimal | None, Decimal | None]:
    st = stats_by_ticker.get(ticker) or {}
    high_3m = st.get("high_3m")
    avg_52w = st.get("avg_52w")
    if high_3m is not None and not isinstance(high_3m, Decimal):
        high_3m = Decimal(str(high_3m))
    if avg_52w is not None and not isinstance(avg_52w, Decimal):
        avg_52w = Decimal(str(avg_52w))
    return high_3m, avg_52w


def _fetch_stats_for_rows(
    rows: Sequence[PositionDcaRow],
    *,
    history_fetcher: HistoryStatsFetcher | None,
    fetch_history: bool,
) -> tuple[dict[str, HistoryStats], bool]:
    if not fetch_history or not rows:
        return {}, False
    ac_map = {r.ticker: r.asset_class for r in rows}
    tickers = [r.ticker for r in rows]
    try:
        if history_fetcher is not None:
            return history_fetcher(tickers, ac_map), True
        stats = fetch_history_stats_yfinance(tickers, ac_map)
        return stats, bool(stats)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DCA history fetch failed open: %s", exc)
        return {}, False


def board_item_dict(
    row: PositionDcaRow,
    m: DcaMetrics,
    *,
    as_of: date,
    high_3m: Decimal | None,
    avg_52w: Decimal | None,
) -> dict[str, Any]:
    blockers = gate_blockers(row, as_of=as_of)
    eligible = not blockers and (m.signal_a or m.signal_b)
    crypto = _is_crypto(row.asset_class)
    level: str | None = None
    if eligible:
        level = "warn" if m.discount_vs_cost_pct >= _warn_discount_threshold(crypto) else "info"
    return {
        "ticker": row.ticker,
        "asset_class": row.asset_class,
        "score": round(m.score, 4),
        "eligible": eligible,
        "level": level,
        "discount_vs_cost_pct": round(m.discount_vs_cost_pct, 2),
        "pullback_pct": round(m.pullback_pct, 2) if m.pullback_pct is not None else None,
        "below_52w_avg_pct": (
            round(m.below_52w_avg_pct, 2) if m.below_52w_avg_pct is not None else None
        ),
        "signal_a": m.signal_a,
        "signal_b": m.signal_b,
        "mark": _q2_str(row.mark),
        "avg_cost_usd": _q2_str(row.avg_cost),
        "market_value_usd": _q2_str(row.mv_usd),
        "cost_basis_usd": _q2_str(row.cost_usd),
        "days_since_buy": row.days_since_buy,
        "last_buy": row.last_buy.isoformat(),
        "weight_pct": round(row.weight_pct, 2),
        "gate_blockers": blockers,
        "high_3m": _q2_str(high_3m) if high_3m is not None else None,
        "avg_52w": _q2_str(avg_52w) if avg_52w is not None else None,
    }


def build_dca_board(
    lots: Sequence[InvestmentLot],
    events: Sequence[InvestmentEvent],
    prices: Mapping[str, Price],
    *,
    as_of: date | None = None,
    history_fetcher: HistoryStatsFetcher | None = None,
    fetch_history: bool = True,
) -> dict[str, Any]:
    """
    Full DCA board: all material open priced names, split stocks/crypto, score-ranked.
    """
    as_of = as_of or date.today()
    rows = build_position_dca_rows(lots, events, prices, as_of=as_of)
    board_rows = [r for r in rows if r.position_usd >= DCA_BOARD_MIN_POSITION_USD]
    stats_by_ticker, hist_ok = _fetch_stats_for_rows(
        board_rows, history_fetcher=history_fetcher, fetch_history=fetch_history
    )

    stocks: list[dict[str, Any]] = []
    crypto: list[dict[str, Any]] = []
    for r in board_rows:
        high_3m, avg_52w = _normalize_stats(stats_by_ticker, r.ticker)
        m = compute_dca_metrics(r, high_3m=high_3m, avg_52w=avg_52w)
        item = board_item_dict(r, m, as_of=as_of, high_3m=high_3m, avg_52w=avg_52w)
        if _is_crypto(r.asset_class):
            crypto.append(item)
        else:
            stocks.append(item)

    stocks.sort(key=lambda x: (-float(x["score"]), x["ticker"]))
    crypto.sort(key=lambda x: (-float(x["score"]), x["ticker"]))

    return {
        "as_of": as_of.isoformat(),
        "stocks": stocks,
        "crypto": crypto,
        "meta": {
            "history_available": hist_ok,
            "board_min_position_usd": str(DCA_BOARD_MIN_POSITION_USD),
            "alert_min_position_usd": str(DCA_MIN_POSITION_USD),
            "cooldown_days": DCA_COOLDOWN_DAYS,
            "max_weight_pct": DCA_MAX_WEIGHT_PCT,
        },
    }


def build_dca_alerts(
    lots: Sequence[InvestmentLot],
    events: Sequence[InvestmentEvent],
    prices: Mapping[str, Price],
    *,
    as_of: date | None = None,
    history_fetcher: HistoryStatsFetcher | None = None,
    fetch_history: bool = True,
) -> list[dict[str, Any]]:
    """
    Evaluate open book for DCA alerts. Optional history_fetcher for tests;
    production uses yfinance when fetch_history=True.
    """
    as_of = as_of or date.today()
    rows = build_position_dca_rows(lots, events, prices, as_of=as_of)
    if not rows:
        return []

    # Cheap pre-filter before any network I/O: material, cooldown, concentration, fresh price
    pre: list[PositionDcaRow] = []
    for r in rows:
        if r.position_usd < DCA_MIN_POSITION_USD:
            continue
        if r.days_since_buy < DCA_COOLDOWN_DAYS:
            continue
        if r.weight_pct > DCA_MAX_WEIGHT_PCT:
            continue
        if (as_of - r.price_as_of).days > DCA_STALE_PRICE_DAYS:
            continue
        pre.append(r)

    stats_by_ticker, _ = _fetch_stats_for_rows(
        pre, history_fetcher=history_fetcher, fetch_history=fetch_history
    )

    candidates: list[DcaCandidate] = []
    for r in pre:
        high_3m, avg_52w = _normalize_stats(stats_by_ticker, r.ticker)
        c = evaluate_dca_opportunity(
            r, as_of=as_of, high_3m=high_3m, avg_52w=avg_52w
        )
        if c is not None:
            candidates.append(c)

    top = select_top_dca_candidates(candidates)
    return candidates_to_alerts(top, total_eligible=len(candidates))


def build_dca_board_from_repo(
    repo: Any,
    *,
    as_of: date | None = None,
    fetch_history: bool = True,
    history_fetcher: HistoryStatsFetcher | None = None,
) -> dict[str, Any]:
    """Load lots/events/prices from a Sheets repository and build the board."""
    from backend.schema.models import InvestmentEvent, InvestmentLot, Price

    lots = [
        r
        for r in repo.list_rows("InvestmentLots")
        if isinstance(r, InvestmentLot)
    ]
    events = [
        r
        for r in repo.list_rows("InvestmentEvents")
        if isinstance(r, InvestmentEvent)
    ]
    prices = {
        p.ticker.upper(): p
        for p in repo.list_rows("Prices")
        if isinstance(p, Price) and not p.archived
    }
    return build_dca_board(
        lots,
        events,
        prices,
        as_of=as_of,
        fetch_history=fetch_history,
        history_fetcher=history_fetcher,
    )
