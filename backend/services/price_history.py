"""Historical / intraday price series for open positions (yfinance).

Scopes:
  ticker       — price series for one open ticker
  asset_class  — Stock | Crypto MV: holdings as-of each day × historical prices
  all          — full book MV with the same as-of holdings reconstruction

Ranges:
  1d  → 5m bars (intraday)
  1m…max → daily closes

Does not persist OHLCV to Sheets. Process-level cache only.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Literal

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

from backend.common.timeutil import utc_now
from backend.schema.models import (
    AssetClass,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
)
from backend.services.holdings_timeline import HoldingsTimeline, build_holdings_timeline
from backend.services.prices import _normalize_yahoo_symbol
from backend.sheets.repository import SheetsRepository

logger = logging.getLogger(__name__)

RangeKey = Literal["1d", "7d", "1m", "3m", "6m", "ytd", "1y", "5y"]
ScopeKey = Literal["ticker", "asset_class", "all"]

# Cap buy/sell markers returned with a history series
_MAX_TRADE_MARKERS = 300

# (yfinance period, interval, point_kind)
# 1d uses 5d of 5m bars then trims to session/24h — bare period=1d is empty/fragile at open.
_RANGE_SPEC: dict[str, tuple[str, str, str]] = {
    "1d": ("5d", "5m", "intraday"),
    "7d": ("7d", "1d", "daily"),
    "1m": ("1mo", "1d", "daily"),
    "3m": ("3mo", "1d", "daily"),
    "6m": ("6mo", "1d", "daily"),
    "ytd": ("ytd", "1d", "daily"),
    "1y": ("1y", "1d", "daily"),
    "5y": ("5y", "1d", "daily"),
}

# Process cache: key -> (fetched_monotonic, closes_by_our_ticker)
# Values are list of (timestamp_iso, price)
_HISTORY_CACHE: dict[str, tuple[float, dict[str, list[tuple[str, Decimal]]]]] = {}

SeriesPoint = tuple[str, Decimal]  # iso timestamp, price
HistoryFetcher = Callable[
    [list[str], dict[str, str], str, str],
    dict[str, list[SeriesPoint]],
]


def range_to_yfinance_spec(range_key: str) -> tuple[str, str, str]:
    """Return (period, interval, point_kind)."""
    key = (range_key or "1y").strip().lower()
    if key not in _RANGE_SPEC:
        raise ValueError(
            f"Invalid range {range_key!r}; expected one of {sorted(_RANGE_SPEC)}"
        )
    return _RANGE_SPEC[key]


def range_to_yfinance_period(range_key: str) -> str:
    """Back-compat helper used by tests."""
    return range_to_yfinance_spec(range_key)[0]


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q4(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _str_dec(v: Decimal, places: int = 2) -> str:
    if places == 4:
        return str(_q4(v))
    return str(_q2(v))


def clear_history_cache() -> None:
    """Test helper."""
    _HISTORY_CACHE.clear()


def _index_to_iso(idx: Any, *, intraday: bool) -> str:
    """Normalize index to date (daily) or UTC ISO (intraday) for stable sorting."""
    dt: datetime | None = None
    if hasattr(idx, "to_pydatetime"):
        dt = idx.to_pydatetime()
    elif isinstance(idx, datetime):
        dt = idx
    elif isinstance(idx, date) and not isinstance(idx, datetime):
        return idx.isoformat()
    else:
        s = str(idx)
        if not intraday:
            return s[:10]
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return s[:19] if "T" in s else s[:10]

    if dt is None:
        return str(idx)[:10]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    if intraday:
        return dt.isoformat()
    return dt.date().isoformat()


def _parse_ts(ts: str) -> datetime:
    """Parse series timestamp for chronological sort."""
    if "T" in ts:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return datetime(int(ts[0:4]), int(ts[5:7]), int(ts[8:10]), tzinfo=timezone.utc)


# Default: emit MV once this fraction of the book (by latest mark) is priced.
COVERAGE_THRESHOLD = Decimal("0.90")
# Early session: partial Yahoo coverage is normal — allow thinner book marks.
COVERAGE_THRESHOLD_INTRADAY = Decimal("0.50")


def _et_zone():
    if ZoneInfo is not None:
        try:
            return ZoneInfo("America/New_York")
        except Exception:  # noqa: BLE001
            pass
    return timezone(timedelta(hours=-4))  # EDT fallback


def _to_et(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_et_zone())


def trim_intraday_series(
    series: list[SeriesPoint],
    *,
    mode: Literal["rth_today_or_prior", "last_24h"],
    now: datetime | None = None,
) -> tuple[list[SeriesPoint], str]:
    """
    Trim 5m bars for 1D display.

    rth_today_or_prior — US regular session today; if none yet, prior RTH day.
    last_24h — rolling 24h (portfolio / crypto).
    """
    if not series:
        return [], "empty"

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if mode == "last_24h":
        cutoff = now - timedelta(hours=24)
        out = [(ts, px) for ts, px in series if _parse_ts(ts) >= cutoff]
        return (out if out else series[-min(12, len(series)) :], "last_24h")

    # US RTH: 09:30–16:00 America/New_York
    et = _to_et(now)
    today = et.date()
    session_open = datetime(today.year, today.month, today.day, 9, 30, tzinfo=_et_zone())

    today_bars: list[SeriesPoint] = []
    for ts, px in series:
        tdt = _parse_ts(ts)
        tet = _to_et(tdt)
        if tet.date() == today and tet >= session_open:
            # Keep through session; after-hours 5m usually absent without prepost
            today_bars.append((ts, px))

    if today_bars:
        return today_bars, "regular"

    # Prior complete RTH day: last calendar date before today that has bars in 09:30–16:00 ET
    by_day: dict[date, list[SeriesPoint]] = {}
    for ts, px in series:
        tdt = _parse_ts(ts)
        tet = _to_et(tdt)
        if tet.date() >= today:
            continue
        if tet.hour > 16 or (tet.hour == 16 and tet.minute > 0):
            continue
        if tet.hour < 9 or (tet.hour == 9 and tet.minute < 30):
            continue
        by_day.setdefault(tet.date(), []).append((ts, px))

    if not by_day:
        # Fall back to last 78 bars (~RTH length) of whatever we have
        return series[-min(78, len(series)) :], "prior_session"

    last_day = max(by_day.keys())
    return by_day[last_day], "prior_session"


def trim_closes_map(
    closes: dict[str, list[SeriesPoint]],
    *,
    mode: Literal["rth_today_or_prior", "last_24h"],
    now: datetime | None = None,
) -> tuple[dict[str, list[SeriesPoint]], str]:
    """Trim each ticker; session_status is worst/best summary across tickers."""
    out: dict[str, list[SeriesPoint]] = {}
    statuses: list[str] = []
    for t, series in closes.items():
        trimmed, st = trim_intraday_series(series, mode=mode, now=now)
        if trimmed:
            out[t] = trimmed
            statuses.append(st)
    if not statuses:
        return {}, "empty"
    if all(s == "regular" for s in statuses):
        status = "regular"
    elif any(s == "regular" for s in statuses):
        status = "regular"  # mixed: some names open
    elif any(s == "last_24h" for s in statuses):
        status = "last_24h"
    else:
        status = "prior_session"
    return out, status


def _scalar_decimal(val: Any) -> Decimal | None:
    try:
        if val is None:
            return None
        # pandas scalar / numpy
        if hasattr(val, "item") and not isinstance(val, (bytes, str)):
            try:
                val = val.item()
            except Exception:  # noqa: BLE001
                pass
        f = float(val)
        if f != f:  # NaN
            return None
        return Decimal(str(f))
    except Exception:  # noqa: BLE001
        return None


def _extract_close_series(data: Any, ysym: str) -> Any | None:
    """
    Return a 1-d Close series for ``ysym`` from a yfinance download frame.

    Newer yfinance uses MultiIndex columns in two layouts:
      - (Ticker, Price)  e.g. ('PLTR', 'Close')  when group_by='ticker'
      - (Price, Ticker)  e.g. ('Close', 'PLTR')  single-ticker default
    """
    if data is None or getattr(data, "empty", True):
        return None
    cols = data.columns
    nlevels = getattr(cols, "nlevels", 1)

    if nlevels > 1:
        level0 = list(cols.get_level_values(0))
        # Layout A: ticker first
        if ysym in level0:
            try:
                block = data[ysym]
                if "Close" in block.columns:
                    return block["Close"].dropna()
            except Exception:  # noqa: BLE001
                pass
        # Layout B: price field first
        if "Close" in level0:
            try:
                close_block = data["Close"]
                # DataFrame of tickers, or single Series
                if hasattr(close_block, "columns"):
                    if ysym in close_block.columns:
                        return close_block[ysym].dropna()
                    if len(close_block.columns) == 1:
                        return close_block.iloc[:, 0].dropna()
                else:
                    return close_block.dropna()
            except Exception:  # noqa: BLE001
                pass
        return None

    # Flat columns
    if "Close" in cols:
        close = data["Close"]
        if hasattr(close, "columns"):
            return close.iloc[:, 0].dropna()
        return close.dropna()
    return None


def _series_from_close(close: Any, *, intraday: bool) -> list[SeriesPoint]:
    series: list[SeriesPoint] = []
    if close is None:
        return series
    # Ensure row iteration (Series), not column iteration (DataFrame.items)
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
    try:
        close = close.dropna()
    except Exception:  # noqa: BLE001
        return series
    for idx, val in close.items():
        px = _scalar_decimal(val)
        if px is None:
            continue
        try:
            ts = _index_to_iso(idx, intraday=intraday)
        except Exception:  # noqa: BLE001
            continue
        series.append((ts, px))
    return series


def _yfinance_history_batch(
    yahoo_symbols: list[str],
    yahoo_to_our: dict[str, str],
    period: str,
    interval: str,
) -> dict[str, list[SeriesPoint]]:
    """Fetch closes; keys are our tickers; values (iso_ts, price)."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is not installed") from exc

    if not yahoo_symbols:
        return {}

    intraday = interval != "1d"
    out: dict[str, list[SeriesPoint]] = {}
    try:
        # Always group_by ticker so multi-symbol layout is consistent.
        data = yf.download(
            tickers=yahoo_symbols if len(yahoo_symbols) > 1 else yahoo_symbols[0],
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance history download failed: %s", exc)
        data = None

    for ysym in yahoo_symbols:
        our = yahoo_to_our[ysym]
        series: list[SeriesPoint] = []
        try:
            close = _extract_close_series(data, ysym)
            series = _series_from_close(close, intraday=intraday)
            if not series:
                t = yf.Ticker(ysym)
                hist = t.history(period=period, interval=interval, auto_adjust=True)
                if hist is not None and not hist.empty:
                    hclose = hist["Close"] if "Close" in hist.columns else None
                    series = _series_from_close(hclose, intraday=intraday)
        except Exception as exc:  # noqa: BLE001
            logger.warning("history failed for %s: %s", ysym, exc)
            continue
        if series:
            series.sort(key=lambda x: x[0])
            out[our] = series
    return out


def aggregate_mv_series(
    qty_by_ticker: dict[str, Decimal],
    closes_by_ticker: dict[str, list[SeriesPoint]],
    *,
    coverage_threshold: Decimal = COVERAGE_THRESHOLD,
) -> tuple[list[SeriesPoint], dict[str, Any]]:
    """
    Forward-fill closes per ticker; sum qty * close on each union timestamp.

    Emit a point when priced names cover ``coverage_threshold`` of the book
    (weights = qty × each ticker's **latest** known close). This prevents:
      - ridiculously low early MV (tiny subset of names), and
      - long ranges collapsing to the shortest IPO (e.g. SPCX clips 1Y→6 weeks).

    Tickers with no Yahoo series are omitted (caller reports missing).
    """
    empty_meta: dict[str, Any] = {
        "coverage_threshold": float(coverage_threshold),
        "short_history_tickers": [],
        "series_start": None,
    }
    if not qty_by_ticker:
        return [], empty_meta

    price_maps: dict[str, dict[str, Decimal]] = {}
    first_bar: dict[str, str] = {}
    latest_px: dict[str, Decimal] = {}
    all_ts: set[str] = set()
    for t, series in closes_by_ticker.items():
        if t not in qty_by_ticker:
            continue
        m: dict[str, Decimal] = {}
        for ts, px in series:
            m[ts] = px
            all_ts.add(ts)
        if m:
            price_maps[t] = m
            ordered_ts = sorted(m.keys(), key=_parse_ts)
            first_bar[t] = ordered_ts[0]
            latest_px[t] = m[ordered_ts[-1]]

    if not all_ts or not price_maps:
        return [], empty_meta

    # Weight by latest mark so small penny names don't dominate the gate
    weights: dict[str, Decimal] = {}
    for t in price_maps:
        qty = qty_by_ticker.get(t, Decimal("0"))
        if qty <= 0:
            continue
        weights[t] = qty * latest_px[t]
    total_weight = sum(weights.values(), Decimal("0"))
    if total_weight <= 0:
        return [], empty_meta

    threshold = coverage_threshold
    ordered = sorted(all_ts, key=_parse_ts)
    last: dict[str, Decimal] = {}
    result: list[SeriesPoint] = []

    for ts in ordered:
        for t, m in price_maps.items():
            if ts in m:
                last[t] = m[ts]
        if not last:
            continue
        covered = sum((weights[t] for t in last if t in weights), Decimal("0"))
        if covered / total_weight < threshold:
            continue
        total = Decimal("0")
        for t, px in last.items():
            qty = qty_by_ticker.get(t, Decimal("0"))
            if qty <= 0:
                continue
            total += qty * px
        result.append((ts, _q2(total)))

    series_start = result[0][0] if result else None
    short: list[dict[str, str]] = []
    if series_start is not None:
        for t, fb in first_bar.items():
            # Joins after the chart has already started (late listing / short Yahoo)
            if _parse_ts(fb) > _parse_ts(series_start):
                short.append({"ticker": t, "first_bar": fb})
        short.sort(key=lambda x: x["ticker"])

    meta = {
        "coverage_threshold": float(threshold),
        "short_history_tickers": short,
        "series_start": series_start,
        "quantity_basis": "constant",
    }
    return result, meta


def _ts_to_date(ts: str) -> date:
    dt = _parse_ts(ts)
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).date()
    return dt.date()


def _series_value_on_or_before(
    series_points: list[dict[str, str]],
    as_of: date,
) -> Decimal | None:
    """Last chart point on or before as_of (by calendar date)."""
    best: Decimal | None = None
    for p in series_points:
        try:
            d0 = _ts_to_date(p["date"])
            v = Decimal(str(p["value"]))
        except Exception:  # noqa: BLE001
            continue
        if d0 <= as_of:
            best = v
        else:
            # points are chronological
            break
    if best is None and series_points:
        # Trade before first bar — snap to first value
        try:
            return Decimal(str(series_points[0]["value"]))
        except Exception:  # noqa: BLE001
            return None
    return best


def collect_trade_markers(
    events: list[InvestmentEvent],
    series_points: list[dict[str, str]],
    *,
    ticker: str | None = None,
    asset_class: AssetClass | None = None,
    asset_class_by_ticker: dict[str, str | None] | None = None,
    max_markers: int = _MAX_TRADE_MARKERS,
) -> list[dict[str, Any]]:
    """
    Buy/Sell markers for the chart window. Excludes staking, allocations, etc.

    ``series_value`` is the MV/price line level on that day so markers sit on the curve.
    """
    if not series_points:
        return []

    window_start = _ts_to_date(series_points[0]["date"])
    window_end = _ts_to_date(series_points[-1]["date"])
    ac_map = asset_class_by_ticker or {}
    want_ticker = ticker.upper() if ticker else None
    want_ac = asset_class.value if asset_class is not None else None

    raw: list[dict[str, Any]] = []
    for e in events:
        if e.archived:
            continue
        if e.event_type not in (InvestmentEventType.BUY, InvestmentEventType.SELL):
            continue
        if not e.ticker or e.quantity is None or e.quantity <= 0:
            continue
        t = e.ticker.upper()
        if want_ticker is not None and t != want_ticker:
            continue
        if want_ac is not None:
            ev_ac = e.asset_class.value if e.asset_class is not None else ac_map.get(t)
            if (ev_ac or "").lower() != want_ac.lower():
                continue
        ed = e.event_date
        if ed < window_start or ed > window_end:
            continue
        side = "buy" if e.event_type == InvestmentEventType.BUY else "sell"
        series_val = _series_value_on_or_before(series_points, ed)
        value_usd = e.value_usd
        raw.append(
            {
                "date": ed.isoformat(),
                "side": side,
                "ticker": t,
                "quantity": str(e.quantity),
                "value_usd": str(value_usd) if value_usd is not None else None,
                "series_value": str(_q2(series_val)) if series_val is not None else None,
            }
        )

    raw.sort(key=lambda m: (m["date"], m["side"], m["ticker"]))
    if len(raw) > max_markers:
        # Keep most recent markers in-window
        raw = raw[-max_markers:]
    return raw


def aggregate_mv_series_time_aware(
    timeline: HoldingsTimeline,
    closes_by_ticker: dict[str, list[SeriesPoint]],
    *,
    tickers: list[str] | None = None,
    coverage_threshold: Decimal = COVERAGE_THRESHOLD,
) -> tuple[list[SeriesPoint], dict[str, Any]]:
    """
    Forward-fill closes; MV(t) = Σ qty(ticker, date(t)) × price(ticker, t).

    Coverage uses **then-owned** book weights (qty × series latest mark as anchor),
    not today's open lots — so early history is not inflated by names bought later.
    """
    empty_meta: dict[str, Any] = {
        "coverage_threshold": float(coverage_threshold),
        "short_history_tickers": [],
        "series_start": None,
        "quantity_basis": "holdings_as_of_each_date",
    }
    universe = [t.upper() for t in (tickers if tickers is not None else timeline.tickers())]
    if not universe:
        return [], empty_meta

    price_maps: dict[str, dict[str, Decimal]] = {}
    first_bar: dict[str, str] = {}
    latest_px: dict[str, Decimal] = {}
    all_ts: set[str] = set()
    for t in universe:
        series = closes_by_ticker.get(t) or []
        if not series:
            continue
        m: dict[str, Decimal] = {}
        for ts, px in series:
            m[ts] = px
            all_ts.add(ts)
        if not m:
            continue
        price_maps[t] = m
        ordered_ts = sorted(m.keys(), key=_parse_ts)
        first_bar[t] = ordered_ts[0]
        latest_px[t] = m[ordered_ts[-1]]

    if not all_ts or not price_maps:
        return [], empty_meta

    threshold = coverage_threshold
    ordered = sorted(all_ts, key=_parse_ts)
    last: dict[str, Decimal] = {}
    result: list[SeriesPoint] = []

    for ts in ordered:
        for t, m in price_maps.items():
            if ts in m:
                last[t] = m[ts]
        if not last:
            continue

        as_of = _ts_to_date(ts)
        owned: dict[str, Decimal] = {}
        for t in price_maps:
            q = timeline.qty_as_of(t, as_of)
            if q > 0:
                owned[t] = q
        if not owned:
            continue

        # Anchor weights: then-owned qty × end-of-series mark (stable gate)
        total_weight = Decimal("0")
        for t, q in owned.items():
            px_anchor = latest_px.get(t)
            if px_anchor is None:
                continue
            total_weight += q * px_anchor
        if total_weight <= 0:
            continue

        covered = Decimal("0")
        total_mv = Decimal("0")
        for t, q in owned.items():
            if t not in last:
                continue
            px = last[t]
            total_mv += q * px
            covered += q * latest_px[t]

        if covered / total_weight < threshold:
            continue
        result.append((ts, _q2(total_mv)))

    series_start = result[0][0] if result else None
    short: list[dict[str, str]] = []
    if series_start is not None:
        for t, fb in first_bar.items():
            if _parse_ts(fb) > _parse_ts(series_start):
                short.append({"ticker": t, "first_bar": fb})
        short.sort(key=lambda x: x["ticker"])

    meta = {
        "coverage_threshold": float(threshold),
        "short_history_tickers": short,
        "series_start": series_start,
        "quantity_basis": "holdings_as_of_each_date",
    }
    return result, meta


def _change_meta(
    first: Decimal | None,
    last: Decimal | None,
    *,
    places: int = 2,
) -> dict[str, Any]:
    change_pct = None
    change_abs = None
    if first is not None and last is not None:
        change_abs = last - first
        if first != 0:
            change_pct = float((change_abs / first) * 100)
    return {
        "first_value": _str_dec(first, places) if first is not None else None,
        "last_value": _str_dec(last, places) if last is not None else None,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "change_abs": _str_dec(change_abs, places) if change_abs is not None else None,
    }


def _day_change_from_series(series: list[SeriesPoint], *, places: int = 2) -> dict[str, Any]:
    if not series:
        return {
            "day_open": None,
            "day_last": None,
            "day_change_pct": None,
            "day_change_abs": None,
        }
    first, last = series[0][1], series[-1][1]
    abs_ch = last - first
    pct = float((abs_ch / first) * 100) if first != 0 else None
    return {
        "day_open": _str_dec(first, places),
        "day_last": _str_dec(last, places),
        "day_change_pct": round(pct, 2) if pct is not None else None,
        "day_change_abs": _str_dec(abs_ch, places),
    }


@dataclass
class HistoryResult:
    scope: str
    label: str
    range: str
    currency: str
    series_kind: str
    interval: str
    as_of: datetime
    points: list[dict[str, str]]
    meta: dict[str, Any] = field(default_factory=dict)


class PriceHistoryService:
    def __init__(
        self,
        repo: SheetsRepository,
        *,
        cache_ttl_seconds: int = 3600,
        intraday_cache_ttl_seconds: int = 90,
        enabled: bool = True,
        fetcher: HistoryFetcher | None = None,
    ) -> None:
        self.repo = repo
        self.cache_ttl = cache_ttl_seconds
        self.intraday_cache_ttl = intraday_cache_ttl_seconds
        self.enabled = enabled
        self._fetcher = fetcher or _yfinance_history_batch

    def _open_lots(self) -> list[InvestmentLot]:
        rows: list[InvestmentLot] = []
        for row in self.repo.list_rows("InvestmentLots"):
            if not isinstance(row, InvestmentLot):
                continue
            if row.archived or row.status != LotStatus.OPEN or row.quantity_remaining <= 0:
                continue
            rows.append(row)
        return rows

    def _all_lots(self) -> list[InvestmentLot]:
        rows: list[InvestmentLot] = []
        for row in self.repo.list_rows("InvestmentLots"):
            if not isinstance(row, InvestmentLot):
                continue
            if row.archived:
                continue
            rows.append(row)
        return rows

    def _all_events(self) -> list[InvestmentEvent]:
        rows: list[InvestmentEvent] = []
        for row in self.repo.list_rows("InvestmentEvents"):
            if not isinstance(row, InvestmentEvent):
                continue
            if row.archived:
                continue
            rows.append(row)
        return rows

    def _qty_and_cost_by_ticker(
        self,
        lots: list[InvestmentLot],
        *,
        asset_class: AssetClass | None = None,
        ticker: str | None = None,
        all_open: bool = False,
    ) -> tuple[dict[str, Decimal], Decimal, dict[str, str | None]]:
        qty: dict[str, Decimal] = {}
        cost = Decimal("0")
        ac_map: dict[str, str | None] = {}
        for lot in lots:
            t = lot.ticker.upper()
            if ticker is not None and t != ticker.upper():
                continue
            if not all_open and asset_class is not None:
                if lot.asset_class is None or lot.asset_class != asset_class:
                    continue
            qty[t] = qty.get(t, Decimal("0")) + lot.quantity_remaining
            cost += lot.cost_basis_usd or Decimal("0")
            if t not in ac_map:
                ac_map[t] = lot.asset_class.value if lot.asset_class else None
        return qty, cost, ac_map

    def _fetch_closes(
        self,
        tickers: list[str],
        asset_classes: dict[str, str | None],
        period: str,
        interval: str,
    ) -> dict[str, list[SeriesPoint]]:
        yahoo_map: dict[str, str] = {}
        equity_syms: list[str] = []
        crypto_syms: list[str] = []
        for t in tickers:
            ac = asset_classes.get(t)
            ysym = _normalize_yahoo_symbol(t, ac)
            yahoo_map[ysym] = t.upper()
            is_crypto = (ac or "").lower() == "crypto" or ysym.endswith("-USD")
            (crypto_syms if is_crypto else equity_syms).append(ysym)

        # Split equity vs crypto batches — mixed 1d/5m MultiIndex NaNs crypto at RTH stamps
        yahoo_symbols = list(yahoo_map.keys())
        session_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cache_key = (
            f"{period}|{interval}|{session_tag}|{'|'.join(sorted(yahoo_symbols))}"
        )
        is_intraday = interval != "1d"
        ttl = self.intraday_cache_ttl if is_intraday else self.cache_ttl
        now_m = time.monotonic()
        if cache_key in _HISTORY_CACHE:
            fetched, payload = _HISTORY_CACHE[cache_key]
            if now_m - fetched <= ttl:
                return payload

        payload: dict[str, list[SeriesPoint]] = {}
        for group in (equity_syms, crypto_syms):
            if not group:
                continue
            sub_map = {ys: yahoo_map[ys] for ys in group}
            part = self._fetcher(group, sub_map, period, interval)
            payload.update(part)

        # Don't pin empty / near-empty intraday results for full TTL (open-flash)
        max_len = max((len(s) for s in payload.values()), default=0)
        if is_intraday and max_len < 3:
            # Short negative cache only
            _HISTORY_CACHE[cache_key] = (time.monotonic() - max(0, ttl - 15), payload)
        else:
            _HISTORY_CACHE[cache_key] = (time.monotonic(), payload)
        return payload

    def _resolve_day_change(
        self,
        qty_map: dict[str, Decimal],
        ac_map: dict[str, str | None],
        *,
        series_kind: str,
        main_range: str,
        main_series: list[SeriesPoint] | None = None,
        places: int = 2,
    ) -> dict[str, Any]:
        """Day open→last change; reuse main series when already on 1d."""
        try:
            if main_range == "1d" and main_series is not None:
                return _day_change_from_series(main_series, places=places)
            tickers = sorted(qty_map.keys())
            if not tickers:
                return _day_change_from_series([], places=places)
            closes = self._fetch_closes(tickers, ac_map, "1d", "5m")
            if series_kind == "price":
                t = tickers[0]
                return _day_change_from_series(closes.get(t, []), places=places)
            mv, _agg_meta = aggregate_mv_series(qty_map, closes)
            return _day_change_from_series(mv, places=places)
        except Exception as exc:  # noqa: BLE001
            logger.warning("day change resolve failed: %s", exc)
            return _day_change_from_series([], places=places)

    def history(
        self,
        *,
        scope: ScopeKey | str,
        range_key: RangeKey | str = "1y",
        ticker: str | None = None,
        asset_class: str | None = None,
    ) -> HistoryResult:
        if not self.enabled:
            raise RuntimeError("yfinance disabled")

        period, interval, point_kind = range_to_yfinance_spec(str(range_key))
        range_norm = str(range_key).strip().lower()
        lots = self._open_lots()
        ts = utc_now()
        places = 4 if scope == "ticker" else 2
        is_intraday = point_kind == "intraday"
        cov_threshold = (
            COVERAGE_THRESHOLD_INTRADAY if is_intraday else COVERAGE_THRESHOLD
        )

        if scope == "ticker":
            if not ticker or not ticker.strip():
                raise ValueError("ticker is required when scope=ticker")
            t = ticker.strip().upper()
            qty_map, cost, ac_map = self._qty_and_cost_by_ticker(lots, ticker=t)
            if not qty_map:
                raise LookupError(f"No open position for {t}")
            closes = self._fetch_closes([t], ac_map, period, interval)
            session_status = "regular"
            if is_intraday:
                ac = (ac_map.get(t) or "").lower()
                mode: Literal["rth_today_or_prior", "last_24h"] = (
                    "last_24h" if ac == "crypto" else "rth_today_or_prior"
                )
                closes, session_status = trim_closes_map(closes, mode=mode)
            series = closes.get(t, [])
            missing = [] if series else [t]
            qty = qty_map[t]
            avg_cost = (cost / qty) if qty > 0 else None
            points = [
                {"date": d_ts, "value": _str_dec(px, places)} for d_ts, px in series
            ]
            first = series[0][1] if series else None
            last = series[-1][1] if series else None
            ch = _change_meta(first, last, places=places)
            day = self._resolve_day_change(
                qty_map,
                ac_map,
                series_kind="price",
                main_range=range_norm,
                main_series=series if range_norm == "1d" else None,
                places=places,
            )
            ysym = _normalize_yahoo_symbol(t, ac_map.get(t))
            note = (
                "Intraday (5m) USD. Avg cost from open lots · buy/sell markers."
                if point_kind == "intraday"
                else "Daily close (USD). Avg cost from open lots · buy/sell markers."
            )
            if is_intraday and session_status == "prior_session":
                note = "Prior regular session (today’s open not in Yahoo yet). " + note
            elif is_intraday and session_status == "regular" and len(series) <= 3:
                note = f"Session open · {len(series)} bar(s). " + note
            if missing:
                note = f"No Yahoo history for {ysym}. " + note
            trades = collect_trade_markers(
                self._all_events(),
                points,
                ticker=t,
            )
            return HistoryResult(
                scope="ticker",
                label=t,
                range=range_norm,
                currency="USD",
                series_kind="price",
                interval=interval,
                as_of=ts,
                points=points,
                meta={
                    "tickers": [t],
                    "missing_tickers": missing,
                    "yahoo_symbol": ysym,
                    "cost_basis_usd": _str_dec(cost),
                    "avg_cost_usd": _str_dec(avg_cost, 4) if avg_cost is not None else None,
                    "quantity": str(_q4(qty)),
                    "quantity_basis": "current_open_lots",
                    "trades": trades,
                    "session_status": session_status if is_intraday else None,
                    "note": note,
                    "point_kind": point_kind,
                    **ch,
                    **day,
                },
            )

        # asset_class or all — time-aware holdings (events as-of each date)
        ac_filter: AssetClass | None = None
        label = "Portfolio"
        if scope == "asset_class":
            if not asset_class or not asset_class.strip():
                raise ValueError("asset_class is required when scope=asset_class")
            ac_raw = asset_class.strip()
            try:
                ac_filter = AssetClass(ac_raw)
            except ValueError as exc:
                try:
                    ac_filter = AssetClass(ac_raw.capitalize())
                except ValueError:
                    raise ValueError(
                        f"Invalid asset_class {asset_class!r}; expected Stock or Crypto"
                    ) from exc
            label = ac_filter.value
        elif scope == "all":
            label = "Portfolio"
        else:
            raise ValueError(f"Invalid scope {scope!r}")

        all_lots = self._all_lots()
        events = self._all_events()
        timeline = build_holdings_timeline(events, all_lots)
        if ac_filter is not None:
            tickers = timeline.tickers_for_asset_class(ac_filter)
        else:
            tickers = timeline.tickers()
        if not tickers:
            # Fall back to current open lots if timeline empty (sparse data)
            open_lots = lots
            qty_map, cost, ac_map = self._qty_and_cost_by_ticker(
                open_lots,
                asset_class=ac_filter,
                all_open=ac_filter is None,
            )
            if not qty_map:
                raise LookupError(
                    f"No open {ac_filter.value} positions"
                    if ac_filter
                    else "No open positions"
                )
            tickers = sorted(qty_map.keys())
            closes = self._fetch_closes(tickers, ac_map, period, interval)
            session_status = "regular"
            if is_intraday:
                trim_mode: Literal["rth_today_or_prior", "last_24h"] = (
                    "last_24h"
                    if ac_filter is None or ac_filter == AssetClass.CRYPTO
                    else "rth_today_or_prior"
                )
                closes, session_status = trim_closes_map(closes, mode=trim_mode)
            missing = [t for t in tickers if t not in closes or not closes[t]]
            mv_series, agg_meta = aggregate_mv_series(
                qty_map, closes, coverage_threshold=cov_threshold
            )
            quantity_basis = "current_open_lots"
            note = (
                "Fallback: current holdings × historical prices (no event timeline)."
            )
        else:
            # Current open cost for reference only (not historical cost series)
            open_lots = lots
            _cur_qty, cost, ac_open = self._qty_and_cost_by_ticker(
                open_lots,
                asset_class=ac_filter,
                all_open=ac_filter is None,
            )
            ac_map = {t: timeline.asset_class.get(t) for t in tickers}
            for t, ac in ac_open.items():
                if ac_map.get(t) is None:
                    ac_map[t] = ac
            closes = self._fetch_closes(tickers, ac_map, period, interval)
            session_status = "regular"
            if is_intraday:
                trim_mode = (
                    "last_24h"
                    if ac_filter is None or ac_filter == AssetClass.CRYPTO
                    else "rth_today_or_prior"
                )
                closes, session_status = trim_closes_map(closes, mode=trim_mode)
            missing = [t for t in tickers if t not in closes or not closes[t]]
            mv_series, agg_meta = aggregate_mv_series_time_aware(
                timeline,
                closes,
                tickers=tickers,
                coverage_threshold=cov_threshold,
            )
            quantity_basis = "holdings_as_of_each_date"
            note = (
                "Holdings as of each day × historical prices (intraday 5m) · buy/sell markers."
                if point_kind == "intraday"
                else (
                    "Holdings as of each day × historical closes "
                    "(≥90% then-owned coverage) · buy/sell markers from statements."
                )
            )
            # Day-change uses *today's* as-of qty (not constant open lots)
            today = date.today()
            qty_map = {
                t: q
                for t, q in (
                    (t, timeline.qty_as_of(t, today)) for t in tickers
                )
                if q > 0
            }

        points = [{"date": d_ts, "value": _str_dec(v)} for d_ts, v in mv_series]
        first = mv_series[0][1] if mv_series else None
        last = mv_series[-1][1] if mv_series else None
        ch = _change_meta(first, last, places=2)
        if quantity_basis == "holdings_as_of_each_date":
            day = self._resolve_day_change(
                qty_map if qty_map else {t: Decimal("0") for t in tickers},
                ac_map,
                series_kind="market_value",
                main_range=range_norm,
                main_series=mv_series if range_norm == "1d" else None,
                places=2,
            )
        else:
            day = self._resolve_day_change(
                qty_map,
                ac_map,
                series_kind="market_value",
                main_range=range_norm,
                main_series=mv_series if range_norm == "1d" else None,
                places=2,
            )
        short = agg_meta.get("short_history_tickers") or []
        if short:
            bits = [f"{s['ticker']} from {s['first_bar']}" for s in short[:8]]
            note += " Late listings: " + ", ".join(bits)
            if len(short) > 8:
                note += "…"
        if is_intraday and session_status == "prior_session":
            note = "Prior regular session (today’s open not in Yahoo yet). " + note
        elif is_intraday and session_status == "last_24h":
            note = "Last 24h (5m). " + note
        elif is_intraday and len(mv_series) <= 3:
            note = f"Session open · {len(mv_series)} bar(s). " + note
        trades = collect_trade_markers(
            events,
            points,
            asset_class=ac_filter,
            asset_class_by_ticker=ac_map,
        )
        return HistoryResult(
            scope="all" if scope == "all" else "asset_class",
            label=label,
            range=range_norm,
            currency="USD",
            series_kind="market_value",
            interval=interval,
            as_of=ts,
            points=points,
            meta={
                "tickers": tickers,
                "missing_tickers": missing,
                "coverage_threshold": agg_meta.get("coverage_threshold"),
                "short_history_tickers": short,
                "series_start": agg_meta.get("series_start"),
                "cost_basis_usd": _str_dec(cost),
                "avg_cost_usd": None,
                "quantity": None,
                "quantity_basis": quantity_basis,
                "trades": trades,
                "session_status": session_status if is_intraday else None,
                "note": note,
                "point_kind": point_kind,
                **ch,
                **day,
            },
        )
