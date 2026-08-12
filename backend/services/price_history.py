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


def _prior_rth_close(
    series: list[SeriesPoint],
    *,
    before: datetime,
) -> Decimal | None:
    """Last US RTH close strictly before ``before`` (for overnight carry)."""
    best_px: Decimal | None = None
    best_ts: datetime | None = None
    for ts, px in series:
        tdt = _parse_ts(ts)
        if tdt.tzinfo is None:
            tdt = tdt.replace(tzinfo=timezone.utc)
        if tdt >= before:
            continue
        tet = _to_et(tdt)
        if tet.hour < 9 or (tet.hour == 9 and tet.minute < 30):
            continue
        if tet.hour > 16 or (tet.hour == 16 and tet.minute > 0):
            continue
        if best_ts is None or tdt > best_ts:
            best_ts = tdt
            best_px = px
    return best_px


def _snap_down_5m(dt: datetime) -> datetime:
    """Floor to 5-minute UTC boundary."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    minute = (dt.minute // 5) * 5
    return dt.replace(minute=minute, second=0, microsecond=0)


def _series_to_sorted_pairs(series: list[SeriesPoint]) -> list[tuple[datetime, Decimal]]:
    pairs: list[tuple[datetime, Decimal]] = []
    for ts, px in series:
        tdt = _parse_ts(ts)
        if tdt.tzinfo is None:
            tdt = tdt.replace(tzinfo=timezone.utc)
        else:
            tdt = tdt.astimezone(timezone.utc)
        pairs.append((tdt, px))
    pairs.sort(key=lambda x: x[0])
    return pairs


def _px_asof(
    pairs: list[tuple[datetime, Decimal]],
    asof: datetime,
    *,
    start_i: int = 0,
) -> tuple[Decimal | None, int]:
    """Last price at or before asof; return (px, new_index_hint)."""
    if not pairs:
        return None, start_i
    i = start_i
    n = len(pairs)
    while i + 1 < n and pairs[i + 1][0] <= asof:
        i += 1
    if pairs[i][0] <= asof:
        return pairs[i][1], i
    return None, i


def build_portfolio_1d_aligned_closes(
    closes_full: dict[str, list[SeriesPoint]],
    asset_classes: dict[str, str | None],
    *,
    now: datetime | None = None,
) -> tuple[dict[str, list[SeriesPoint]], str]:
    """
    Portfolio 1D on a **shared 5m UTC grid** over the last 24h.

    Every ticker gets a mark on every grid timestamp (forward-filled):
      - Equity: previous RTH close until the first live RTH bar, then live
      - Crypto: live 5m with forward-fill

    Same timestamps for all names → no stock/crypto seed desync, no partial-book
    first bar, additive window Δ ≈ stocks session + crypto 24h.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    window_open = _snap_down_5m(now - timedelta(hours=24))
    window_end = _snap_down_5m(now)

    grid: list[datetime] = []
    t = window_open
    while t <= window_end:
        grid.append(t)
        t += timedelta(minutes=5)
    if not grid:
        return {}, "empty"

    out: dict[str, list[SeriesPoint]] = {}
    for ticker, full in closes_full.items():
        if not full:
            continue
        ac = (asset_classes.get(ticker) or "").lower()
        is_crypto = ac == "crypto"
        pairs = _series_to_sorted_pairs(full)
        if not pairs:
            continue

        # Opening mark for the window
        if is_crypto:
            open_px, _ = _px_asof(pairs, window_open)
            if open_px is None:
                # First print in window
                for pdt, px in pairs:
                    if pdt >= window_open:
                        open_px = px
                        break
            if open_px is None:
                open_px = pairs[0][1]
        else:
            open_px = _prior_rth_close(full, before=window_open)
            if open_px is None:
                open_px, _ = _px_asof(pairs, window_open)
            if open_px is None:
                open_px = pairs[0][1]

        series_out: list[SeriesPoint] = []
        last_px = open_px
        hint = 0
        for g in grid:
            live, hint = _px_asof(pairs, g, start_i=hint)
            if live is not None:
                # Equities: only adopt live prints once we're at/after that bar
                # (prior close already in last_px overnight)
                last_px = live
            series_out.append(
                (g.replace(microsecond=0).isoformat(), last_px)
            )
        out[ticker] = series_out

    if not out:
        return {}, "empty"
    return out, "last_24h"


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


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _series_is_intraday(series_points: list[dict[str, str]]) -> bool:
    """True when any point is a full ISO timestamp (5m / 1d charts)."""
    return any("T" in str(p.get("date", "")) for p in series_points)


def _event_ts(e: InvestmentEvent) -> datetime:
    """Event instant for window filter; start-of-day UTC when time unknown."""
    if e.event_datetime is not None:
        return _as_utc(e.event_datetime)
    return datetime(e.event_date.year, e.event_date.month, e.event_date.day, tzinfo=timezone.utc)


def _snap_series_point(
    series_points: list[dict[str, str]],
    as_of: datetime,
) -> tuple[str | None, Decimal | None]:
    """
    Last series bar on or before ``as_of`` (by full timestamp).

    Returns (point date string as stored, value). Snaps before-window trades
    to the first bar so markers still land on the curve.
    """
    as_of_u = _as_utc(as_of)
    best_date: str | None = None
    best_val: Decimal | None = None
    for p in series_points:
        try:
            pts = _as_utc(_parse_ts(p["date"]))
            v = Decimal(str(p["value"]))
        except Exception:  # noqa: BLE001
            continue
        if pts <= as_of_u:
            best_date = p["date"]
            best_val = v
        else:
            break
    if best_date is None and series_points:
        try:
            return series_points[0]["date"], Decimal(str(series_points[0]["value"]))
        except Exception:  # noqa: BLE001
            return series_points[0].get("date"), None
    return best_date, best_val


def _series_value_on_or_before(
    series_points: list[dict[str, str]],
    as_of: date,
) -> Decimal | None:
    """Last chart point on or before as_of (by calendar date) — daily series."""
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


def _series_day_on_or_before(
    series_points: list[dict[str, str]],
    as_of: date,
) -> str | None:
    """Calendar day key (YYYY-MM-DD) of last daily series bar on or before as_of."""
    best: str | None = None
    for p in series_points:
        try:
            d0 = _ts_to_date(p["date"])
        except Exception:  # noqa: BLE001
            continue
        if d0 <= as_of:
            best = p["date"][:10]
        else:
            break
    if best is None and series_points:
        return series_points[0]["date"][:10]
    return best


def densify_daily_closes(
    series: list[SeriesPoint],
    *,
    max_gap_days: int = 3,
) -> list[SeriesPoint]:
    """
    Forward-fill short interior holes in a daily series (crypto Yahoo gaps).

    Only fills gaps of 1..max_gap_days calendar days between consecutive bars
    so multi-month sparse fixtures / long ranges are not exploded into every day.
    Skips intraday (ISO-T) series.
    """
    if len(series) < 2:
        return series
    if any("T" in ts for ts, _ in series):
        return series
    # Sort by date
    ordered = sorted(series, key=lambda p: p[0][:10])
    out: list[SeriesPoint] = [ordered[0]]
    for i in range(1, len(ordered)):
        prev_ts, prev_px = out[-1]
        cur_ts, cur_px = ordered[i]
        try:
            prev_d = date.fromisoformat(prev_ts[:10])
            cur_d = date.fromisoformat(cur_ts[:10])
        except ValueError:
            out.append((cur_ts[:10], cur_px))
            continue
        gap = (cur_d - prev_d).days
        if 1 < gap <= max_gap_days:
            d = prev_d + timedelta(days=1)
            while d < cur_d:
                out.append((d.isoformat(), prev_px))
                d += timedelta(days=1)
        out.append((cur_ts[:10], cur_px))
    return out


def densify_crypto_closes_map(
    closes: dict[str, list[SeriesPoint]],
    asset_classes: dict[str, str | None],
) -> dict[str, list[SeriesPoint]]:
    """Densify daily crypto series only; leave equities as market-day bars."""
    out: dict[str, list[SeriesPoint]] = {}
    for t, series in closes.items():
        ac = (asset_classes.get(t) or "").lower()
        ysym_crypto = t.upper().endswith("-USD")  # defensive
        if ac == "crypto" or ysym_crypto:
            out[t] = densify_daily_closes(series)
        else:
            out[t] = series
    return out


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

    Daily series: filter by calendar day; marker ``date`` is YYYY-MM-DD.
    Intraday series: filter by full timestamp against first/last bar; marker
    ``date`` is snapped to a series bar timestamp so the UI attaches once.
    ``series_value`` is the MV/price line level on that bar.
    """
    if not series_points:
        return []

    intraday = _series_is_intraday(series_points)
    if intraday:
        win_start = _as_utc(_parse_ts(series_points[0]["date"]))
        win_end = _as_utc(_parse_ts(series_points[-1]["date"]))
        window_start_d: date | None = None
        window_end_d: date | None = None
    else:
        win_start = win_end = None  # type: ignore[assignment]
        window_start_d = _ts_to_date(series_points[0]["date"])
        window_end_d = _ts_to_date(series_points[-1]["date"])

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

        # Window filter + snap.
        # Yahoo series often ends *before* the latest statement trade (stale 5m
        # bar, or daily chart with no "today" close yet). Trades after the last
        # bar but still on the last bar's calendar day — or on the next day when
        # the series is one day behind — snap to the last bar so they stay visible.
        if intraday:
            ets = _event_ts(e)
            assert win_start is not None and win_end is not None
            if ets < win_start:
                continue
            if ets > win_end:
                last_day = win_end.date()
                eday = ets.date()
                # Same day as last bar, or next calendar day (series lag).
                if eday != last_day and eday != last_day + timedelta(days=1):
                    continue
                snapped_date = series_points[-1]["date"]
                try:
                    series_val = Decimal(str(series_points[-1]["value"]))
                except Exception:  # noqa: BLE001
                    series_val = None
                marker_date = snapped_date
            else:
                snapped_date, series_val = _snap_series_point(series_points, ets)
                marker_date = snapped_date or ets.isoformat()
        else:
            ed = e.event_date
            assert window_start_d is not None and window_end_d is not None
            if ed < window_start_d:
                continue
            if ed > window_end_d:
                # Daily series often has no bar for "today" yet.
                if ed > window_end_d + timedelta(days=1):
                    continue
                # Snap onto last series day so the FE day-key still attaches.
                marker_date = series_points[-1]["date"][:10]
                series_val = _series_value_on_or_before(series_points, window_end_d)
            else:
                # Interior Yahoo holes (e.g. missing Aug 11 between 10 and 12):
                # marker date must be a series day key or FE attach orphans the trade.
                snap_day = _series_day_on_or_before(series_points, ed)
                if snap_day is None:
                    continue
                marker_date = snap_day
                series_val = _series_value_on_or_before(series_points, ed)

        side = "buy" if e.event_type == InvestmentEventType.BUY else "sell"
        value_usd = e.value_usd
        raw.append(
            {
                "date": marker_date,
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


def _event_flow_usd(e: InvestmentEvent) -> Decimal | None:
    """USD cash impact of a buy/sell when available."""
    if e.value_usd is not None:
        return abs(_d_safe(e.value_usd))
    if e.native_currency and e.native_currency.upper() == "USD" and e.value_native is not None:
        return abs(_d_safe(e.value_native))
    return None


def _d_safe(v: Decimal | None) -> Decimal:
    if v is None:
        return Decimal("0")
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _trade_in_series_window(
    e: InvestmentEvent,
    series_points: list[dict[str, str]],
    *,
    ticker: str | None = None,
    asset_class: AssetClass | None = None,
    asset_class_by_ticker: dict[str, str | None] | None = None,
) -> bool:
    """True if Buy/Sell falls in the same window as trade markers."""
    if not series_points:
        return False
    if e.archived:
        return False
    if e.event_type not in (InvestmentEventType.BUY, InvestmentEventType.SELL):
        return False
    if not e.ticker or e.quantity is None or e.quantity <= 0:
        return False
    t = e.ticker.upper()
    want_ticker = ticker.upper() if ticker else None
    if want_ticker is not None and t != want_ticker:
        return False
    ac_map = asset_class_by_ticker or {}
    if asset_class is not None:
        want_ac = asset_class.value
        ev_ac = e.asset_class.value if e.asset_class is not None else ac_map.get(t)
        if (ev_ac or "").lower() != want_ac.lower():
            return False

    intraday = _series_is_intraday(series_points)
    if intraday:
        win_start = _as_utc(_parse_ts(series_points[0]["date"]))
        win_end = _as_utc(_parse_ts(series_points[-1]["date"]))
        ets = _event_ts(e)
        if ets < win_start:
            return False
        if ets > win_end:
            last_day = win_end.date()
            eday = ets.date()
            if eday != last_day and eday != last_day + timedelta(days=1):
                return False
        return True
    window_start_d = _ts_to_date(series_points[0]["date"])
    window_end_d = _ts_to_date(series_points[-1]["date"])
    ed = e.event_date
    if ed < window_start_d:
        return False
    if ed > window_end_d:
        if ed > window_end_d + timedelta(days=1):
            return False
    return True


def window_external_flows(
    events: list[InvestmentEvent],
    series_points: list[dict[str, str]],
    *,
    ticker: str | None = None,
    asset_class: AssetClass | None = None,
    asset_class_by_ticker: dict[str, str | None] | None = None,
) -> dict[str, Decimal]:
    """
    Sum of buy/sell USD in the chart window (external capital to the book).

    performance = ΔMV − buys + sells
    """
    buys = Decimal("0")
    sells = Decimal("0")
    buy_n = 0
    sell_n = 0
    for e in events:
        if not _trade_in_series_window(
            e,
            series_points,
            ticker=ticker,
            asset_class=asset_class,
            asset_class_by_ticker=asset_class_by_ticker,
        ):
            continue
        flow = _event_flow_usd(e)
        if flow is None or flow <= 0:
            continue
        if e.event_type == InvestmentEventType.BUY:
            buys += flow
            buy_n += 1
        else:
            sells += flow
            sell_n += 1
    return {
        "buys_usd": _q2(buys),
        "sells_usd": _q2(sells),
        "net_invested_usd": _q2(buys - sells),
        "buy_count": Decimal(buy_n),
        "sell_count": Decimal(sell_n),
    }


def _price_on_or_before(
    series: list[SeriesPoint],
    as_of_ts: str,
) -> Decimal | None:
    """Last price at or before chart timestamp (forward-fill friendly)."""
    if not series:
        return None
    as_of = _parse_ts(as_of_ts)
    best: Decimal | None = None
    for ts, px in sorted(series, key=lambda p: _parse_ts(p[0])):
        if _parse_ts(ts) <= as_of:
            try:
                best = px if isinstance(px, Decimal) else Decimal(str(px))
            except Exception:  # noqa: BLE001
                continue
        else:
            break
    if best is not None:
        return best
    # Before first print: use first available (still gate qty separately)
    try:
        ordered = sorted(series, key=lambda p: _parse_ts(p[0]))
        px = ordered[0][1]
        return px if isinstance(px, Decimal) else Decimal(str(px))
    except Exception:  # noqa: BLE001
        return None


def _qty_at_chart_open(timeline: HoldingsTimeline, ticker: str, first_ts: str) -> Decimal:
    """
    Qty held **entering** the chart window (excludes buys at/after first bar).

    Daily: end of prior calendar day.
    Intraday: events strictly before first bar timestamp.
    """
    if "T" in first_ts:
        return timeline.qty_as_of_ts(
            ticker, _as_utc(_parse_ts(first_ts)), inclusive=False
        )
    d0 = _ts_to_date(first_ts)
    return timeline.qty_as_of(ticker, d0 - timedelta(days=1))


def window_mark_performance(
    timeline: HoldingsTimeline,
    closes_by_ticker: dict[str, list[SeriesPoint]],
    *,
    tickers: list[str] | None = None,
    chart_first_ts: str | None = None,
    chart_last_ts: str | None = None,
) -> dict[str, Any]:
    """
    Pure mark performance on capital held at **chart window open**.

    For each ticker with prices at both ends of the **chart** window:
      q0 = qty entering the window (no mid-window buys)
      contrib = q0 * (price_at_chart_end − price_at_chart_start)

    Uses shared chart first/last timestamps when provided so performance
    matches the visible series (not each ticker's own Yahoo start/end).
    """
    universe = [
        t.upper()
        for t in (tickers if tickers is not None else list(closes_by_ticker.keys()))
    ]
    # Infer chart bounds from union of series if not provided
    if chart_first_ts is None or chart_last_ts is None:
        all_ts: list[str] = []
        for series in closes_by_ticker.values():
            for ts, _ in series:
                all_ts.append(ts)
        if not all_ts:
            return {
                "performance_abs": Decimal("0.00"),
                "open_basis_usd": Decimal("0.00"),
                "performance_pct": None,
            }
        all_ts.sort(key=_parse_ts)
        chart_first_ts = chart_first_ts or all_ts[0]
        chart_last_ts = chart_last_ts or all_ts[-1]

    assert chart_first_ts is not None and chart_last_ts is not None
    perf = Decimal("0")
    open_basis = Decimal("0")
    for t in universe:
        series = closes_by_ticker.get(t) or []
        if not series:
            continue
        p0 = _price_on_or_before(series, chart_first_ts)
        p1 = _price_on_or_before(series, chart_last_ts)
        if p0 is None or p1 is None:
            continue
        q0 = _qty_at_chart_open(timeline, t, chart_first_ts)
        if q0 <= 0:
            continue
        # Opening-book mark-to-market only (purchases after open excluded)
        perf += q0 * (p1 - p0)
        open_basis += q0 * p0
    return {
        "performance_abs": _q2(perf),
        "open_basis_usd": _q2(open_basis),
        "performance_pct": (
            float((perf / open_basis) * 100) if open_basis != 0 else None
        ),
    }


def performance_change_meta(
    first: Decimal | None,
    last: Decimal | None,
    *,
    performance_abs: Decimal | None = None,
    open_basis_usd: Decimal | None = None,
    performance_pct: float | None = None,
    buys_usd: Decimal = Decimal("0"),
    sells_usd: Decimal = Decimal("0"),
    places: int = 2,
) -> dict[str, Any]:
    """
    Chart-first reconciliation.

    Headline ``change_abs`` / ``change_pct`` = **book Δ** (last − first MV on the
    displayed series). That always matches the chart endpoints.

    When mark performance is available:
      mark_pnl_abs  = q0 × (p_end − p_start) on qty held at window open
      net_capital_abs = book Δ − mark P&L
                        (capital in/out effect: buys positive, sells negative
                         relative to mark when prices rose on sold qty)

    Identity: **Book Δ = Mark P&L + Net capital**.
    """
    mv = _change_meta(first, last, places=places)
    mv_delta = None
    if first is not None and last is not None:
        mv_delta = last - first
    mv_pct = None
    if first is not None and first != 0 and mv_delta is not None:
        mv_pct = float((mv_delta / first) * 100)

    if performance_abs is not None:
        mark = performance_abs
        mark_pct = performance_pct
        if mark_pct is None and open_basis_usd is not None and open_basis_usd != 0:
            mark_pct = float((mark / open_basis_usd) * 100)
        net_cap = None
        if mv_delta is not None:
            net_cap = mv_delta - mark
        return {
            "first_value": _str_dec(first, places) if first is not None else None,
            "last_value": _str_dec(last, places) if last is not None else None,
            # Headline = book (matches chart line)
            "change_abs": _str_dec(mv_delta, places) if mv_delta is not None else None,
            "change_pct": round(mv_pct, 2) if mv_pct is not None else None,
            "mv_change_abs": _str_dec(mv_delta, places) if mv_delta is not None else None,
            "mv_change_pct": round(mv_pct, 2) if mv_pct is not None else None,
            "mark_pnl_abs": _str_dec(mark, places),
            "mark_pnl_pct": round(mark_pct, 2) if mark_pct is not None else None,
            "net_capital_abs": _str_dec(net_cap, places) if net_cap is not None else None,
            "open_basis_usd": (
                _str_dec(open_basis_usd, places) if open_basis_usd is not None else None
            ),
            "window_buys_usd": _str_dec(buys_usd, places),
            "window_sells_usd": _str_dec(sells_usd, places),
            "change_basis": "book_with_mark_reconciliation",
        }

    # Legacy fallback: ΔMV − buys + sells as secondary "mark"; headline still book
    if first is None or last is None:
        return {
            **mv,
            "mv_change_abs": mv.get("change_abs"),
            "mv_change_pct": mv.get("change_pct"),
            "mark_pnl_abs": None,
            "mark_pnl_pct": None,
            "net_capital_abs": None,
            "window_buys_usd": _str_dec(buys_usd, places),
            "window_sells_usd": _str_dec(sells_usd, places),
            "change_basis": "book_only",
        }
    assert mv_delta is not None
    legacy_perf = mv_delta - buys_usd + sells_usd
    legacy_pct = float((legacy_perf / first) * 100) if first != 0 else None
    return {
        "first_value": _str_dec(first, places),
        "last_value": _str_dec(last, places),
        "change_abs": _str_dec(mv_delta, places),
        "change_pct": round(mv_pct, 2) if mv_pct is not None else None,
        "mv_change_abs": _str_dec(mv_delta, places),
        "mv_change_pct": round(mv_pct, 2) if mv_pct is not None else None,
        "mark_pnl_abs": _str_dec(legacy_perf, places),
        "mark_pnl_pct": round(legacy_pct, 2) if legacy_pct is not None else None,
        "net_capital_abs": _str_dec(buys_usd - sells_usd, places),
        "window_buys_usd": _str_dec(buys_usd, places),
        "window_sells_usd": _str_dec(sells_usd, places),
        "change_basis": "book_with_flow_reconciliation",
    }


def aggregate_mv_series_time_aware(
    timeline: HoldingsTimeline,
    closes_by_ticker: dict[str, list[SeriesPoint]],
    *,
    tickers: list[str] | None = None,
    coverage_threshold: Decimal = COVERAGE_THRESHOLD,
    preseed_first_marks: bool = False,
) -> tuple[list[SeriesPoint], dict[str, Any]]:
    """
    Forward-fill closes; MV(t) = Σ qty(ticker, date(t)) × price(ticker, t).

    Coverage uses **then-owned** book weights (qty × series latest mark as anchor),
    not today's open lots — so early history is not inflated by names bought later.

    ``preseed_first_marks``: initialize forward-fill with each series' first mark
    so the first timestamp marks the full priced book (1D portfolio after seed align).
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
    first_px: dict[str, Decimal] = {}
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
        first_px[t] = m[ordered_ts[0]]
        latest_px[t] = m[ordered_ts[-1]]

    if not all_ts or not price_maps:
        return [], empty_meta

    threshold = coverage_threshold
    ordered = sorted(all_ts, key=_parse_ts)
    # Pre-seed so the first bar is full-book (avoids stocks-only partial MV)
    last: dict[str, Decimal] = dict(first_px) if preseed_first_marks else {}
    result: list[SeriesPoint] = []

    # Intraday series use event_datetime so same-day buys do not appear at UTC midnight
    use_ts = any("T" in str(ts) for ts in ordered)

    for ts in ordered:
        for t, m in price_maps.items():
            if ts in m:
                last[t] = m[ts]
        if not last:
            continue

        if use_ts:
            as_of_dt = _parse_ts(ts)
            if as_of_dt.tzinfo is None:
                as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
            else:
                as_of_dt = as_of_dt.astimezone(timezone.utc)
            owned: dict[str, Decimal] = {}
            for t in price_maps:
                q = timeline.qty_as_of_ts(t, as_of_dt)
                if q > 0:
                    owned[t] = q
        else:
            as_of = _ts_to_date(ts)
            owned = {}
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
        "quantity_basis": (
            "holdings_as_of_each_timestamp" if use_ts else "holdings_as_of_each_date"
        ),
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


def _book_mv_window(
    timeline: HoldingsTimeline,
    closes: dict[str, list[SeriesPoint]],
    tickers: list[str],
    *,
    coverage_threshold: Decimal,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Return (first_mv, last_mv, delta) for a book subset, or Nones if empty."""
    if not tickers:
        return None, None, Decimal("0")
    subset = {t: closes[t] for t in tickers if t in closes and closes[t]}
    if not subset:
        return None, None, Decimal("0")
    series, _ = aggregate_mv_series_time_aware(
        timeline,
        subset,
        tickers=tickers,
        coverage_threshold=coverage_threshold,
        preseed_first_marks=True,
    )
    if not series:
        return None, None, Decimal("0")
    first, last = series[0][1], series[-1][1]
    return first, last, last - first


def portfolio_window_from_components(
    timeline: HoldingsTimeline,
    closes_raw: dict[str, list[SeriesPoint]],
    ac_map: dict[str, str | None],
    tickers: list[str],
    *,
    is_intraday: bool,
    coverage_threshold: Decimal,
    events: list[InvestmentEvent] | None = None,
) -> dict[str, Any]:
    """
    Portfolio window **performance** = Stocks leg + Crypto leg, same windows
    as those tabs (RTH vs 24h on 1D).

    Each leg: performance = ΔMV − buys + sells (external capital removed).
    Additive so portfolio = stocks + crypto performance.
    """
    stock_ts = [
        t
        for t in tickers
        if (ac_map.get(t) or "").lower() != "crypto"
    ]
    crypto_ts = [
        t
        for t in tickers
        if (ac_map.get(t) or "").lower() == "crypto"
    ]

    if is_intraday:
        stock_closes, _ = trim_closes_map(
            {t: closes_raw[t] for t in stock_ts if t in closes_raw},
            mode="rth_today_or_prior",
        )
        crypto_closes, _ = trim_closes_map(
            {t: closes_raw[t] for t in crypto_ts if t in closes_raw},
            mode="last_24h",
        )
    else:
        stock_closes = {t: closes_raw[t] for t in stock_ts if t in closes_raw}
        crypto_closes = {t: closes_raw[t] for t in crypto_ts if t in closes_raw}

    s0, s1, s_mv = _book_mv_window(
        timeline, stock_closes, stock_ts, coverage_threshold=coverage_threshold
    )
    c0, c1, c_mv = _book_mv_window(
        timeline, crypto_closes, crypto_ts, coverage_threshold=coverage_threshold
    )
    s_mv = s_mv if s_mv is not None else Decimal("0")
    c_mv = c_mv if c_mv is not None else Decimal("0")

    def _series_bounds(
        closes: dict[str, list[SeriesPoint]],
    ) -> tuple[str | None, str | None]:
        ts_all: list[str] = []
        for series in closes.values():
            for ts, _ in series:
                ts_all.append(ts)
        if not ts_all:
            return None, None
        ts_all.sort(key=_parse_ts)
        return ts_all[0], ts_all[-1]

    s_first, s_last = _series_bounds(stock_closes)
    c_first, c_last = _series_bounds(crypto_closes)
    s_mark = window_mark_performance(
        timeline,
        stock_closes,
        tickers=stock_ts,
        chart_first_ts=s_first,
        chart_last_ts=s_last,
    )
    c_mark = window_mark_performance(
        timeline,
        crypto_closes,
        tickers=crypto_ts,
        chart_first_ts=c_first,
        chart_last_ts=c_last,
    )
    s_perf = s_mark["performance_abs"]
    c_perf = c_mark["performance_abs"]
    total_perf = s_perf + c_perf
    open_basis = s_mark["open_basis_usd"] + c_mark["open_basis_usd"]

    def _flows_for(
        closes: dict[str, list[SeriesPoint]],
        ac: AssetClass,
    ) -> tuple[Decimal, Decimal]:
        if not events or not closes:
            return Decimal("0"), Decimal("0")
        best: list[SeriesPoint] = []
        for series in closes.values():
            if len(series) > len(best):
                best = series
        if not best:
            return Decimal("0"), Decimal("0")
        pts = [{"date": ts, "value": str(px)} for ts, px in best]
        fl = window_external_flows(
            events,
            pts,
            asset_class=ac,
            asset_class_by_ticker=ac_map,
        )
        return fl["buys_usd"], fl["sells_usd"]

    s_buys, s_sells = _flows_for(stock_closes, AssetClass.STOCK)
    c_buys, c_sells = _flows_for(crypto_closes, AssetClass.CRYPTO)

    first_parts = [x for x in (s0, c0) if x is not None]
    first_total = sum(first_parts, Decimal("0")) if first_parts else None
    last_parts = [x for x in (s1, c1) if x is not None]
    last_total = sum(last_parts, Decimal("0")) if last_parts else None

    pct = None
    if open_basis != 0:
        pct = float((total_perf / open_basis) * 100)
    elif first_total is not None and first_total != 0:
        pct = float((total_perf / first_total) * 100)

    def _leg(
        perf: Decimal,
        mv_delta: Decimal,
        first: Decimal | None,
        last: Decimal | None,
        buys: Decimal,
        sells: Decimal,
        open_basis_leg: Decimal,
        perf_pct_leg: float | None,
    ) -> dict[str, Any]:
        leg_pct = perf_pct_leg
        if leg_pct is None and open_basis_leg != 0:
            leg_pct = round(float((perf / open_basis_leg) * 100), 2)
        elif leg_pct is not None:
            leg_pct = round(leg_pct, 2)
        return {
            "change_usd": _str_dec(perf),
            "change_pct": leg_pct,
            "mv_change_usd": _str_dec(mv_delta),
            "window_buys_usd": _str_dec(buys),
            "window_sells_usd": _str_dec(sells),
            "first_usd": _str_dec(first) if first is not None else None,
            "last_usd": _str_dec(last) if last is not None else None,
        }

    return {
        "stocks": _leg(
            s_perf,
            s_mv,
            s0,
            s1,
            s_buys,
            s_sells,
            s_mark["open_basis_usd"],
            s_mark["performance_pct"],
        ),
        "crypto": _leg(
            c_perf,
            c_mv,
            c0,
            c1,
            c_buys,
            c_sells,
            c_mark["open_basis_usd"],
            c_mark["performance_pct"],
        ),
        "sum_change_usd": _str_dec(total_perf),
        "sum_change_pct": round(pct, 2) if pct is not None else None,
        "sum_mv_change_usd": _str_dec(s_mv + c_mv),
        "first_usd": _str_dec(first_total) if first_total is not None else None,
        "last_usd": _str_dec(last_total) if last_total is not None else None,
        "method": (
            "stocks_rth_plus_crypto_24h_mark"
            if is_intraday
            else "stocks_plus_crypto_mark_same_range"
        ),
        "change_basis": "mark_performance_start_qty",
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
        # One-shot: fix Revolut wall-clock-as-UTC so 1D markers land at real times
        try:
            from backend.services.revolut_tz_repair import ensure_revolut_tz_repaired

            ensure_revolut_tz_repaired(self.repo)
        except Exception:  # noqa: BLE001
            pass
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

    def _book_prices_usd(self) -> dict[str, Decimal]:
        """Latest Prices-tab USD marks keyed by ticker."""
        from backend.schema.models import Price

        out: dict[str, Decimal] = {}
        for row in self.repo.list_rows("Prices"):
            if not isinstance(row, Price):
                continue
            t = (row.ticker or "").strip().upper()
            if not t or row.price is None:
                continue
            out[t] = row.price if isinstance(row.price, Decimal) else Decimal(str(row.price))
        return out

    def _book_price_usd(self, ticker: str) -> Decimal | None:
        return self._book_prices_usd().get(ticker.strip().upper())

    def _book_mv_from_qty(self, qty_map: dict[str, Decimal]) -> Decimal | None:
        prices = self._book_prices_usd()
        if not qty_map or not prices:
            return None
        total = Decimal("0")
        any_priced = False
        for t, qty in qty_map.items():
            px = prices.get(t.upper())
            if px is None or qty <= 0:
                continue
            total += qty * px
            any_priced = True
        return _q2(total) if any_priced else None

    def _book_market_value_usd(
        self,
        open_lots: list[InvestmentLot],
        *,
        asset_class: AssetClass | None = None,
    ) -> Decimal | None:
        prices = self._book_prices_usd()
        if not prices:
            return None
        total = Decimal("0")
        any_priced = False
        for lot in open_lots:
            t = lot.ticker.upper()
            if asset_class is not None:
                if lot.asset_class is None or lot.asset_class != asset_class:
                    continue
            px = prices.get(t)
            if px is None:
                continue
            total += lot.quantity_remaining * px
            any_priced = True
        return _q2(total) if any_priced else None

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
            elif (ac_map.get(t) or "").lower() == "crypto":
                closes = densify_crypto_closes_map(closes, ac_map)
            series = closes.get(t, [])
            missing = [] if series else [t]
            qty = qty_map[t]
            avg_cost = (cost / qty) if qty > 0 else None
            # Desk quote for UI parity (never rewrite 1D path — that fakes a cliff).
            # Daily ranges only: pin tip to book so multi-day "last" matches desk.
            book_px = self._book_price_usd(t)
            if (
                not is_intraday
                and book_px is not None
                and series
            ):
                series = list(series)
                last_ts = series[-1][0]
                series[-1] = (last_ts, book_px)
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
                "Intraday (5m) USD path from Yahoo · desk mark is separate (Prices tab)."
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
            meta_ticker: dict[str, Any] = {
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
            }
            if book_px is not None:
                meta_ticker["book_price_usd"] = _str_dec(book_px, places)
                if last is not None:
                    meta_ticker["book_vs_path_abs"] = _str_dec(last - book_px, places)
            return HistoryResult(
                scope="ticker",
                label=t,
                range=range_norm,
                currency="USD",
                series_kind="price",
                interval=interval,
                as_of=ts,
                points=points,
                meta=meta_ticker,
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
        closes_raw: dict[str, list[SeriesPoint]] = {}
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
            closes_raw = self._fetch_closes(tickers, ac_map, period, interval)
            session_status = "regular"
            portfolio_1d = False
            if is_intraday:
                if ac_filter is None:
                    closes, session_status = build_portfolio_1d_aligned_closes(
                        closes_raw, ac_map
                    )
                    portfolio_1d = True
                else:
                    trim_mode: Literal["rth_today_or_prior", "last_24h"] = (
                        "last_24h"
                        if ac_filter == AssetClass.CRYPTO
                        else "rth_today_or_prior"
                    )
                    closes, session_status = trim_closes_map(
                        closes_raw, mode=trim_mode
                    )
            else:
                closes = densify_crypto_closes_map(closes_raw, ac_map)
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
            closes_raw = self._fetch_closes(tickers, ac_map, period, interval)
            session_status = "regular"
            portfolio_1d = False
            if is_intraday:
                if ac_filter is None:
                    # Shared 5m grid — stocks + crypto always marked together
                    closes, session_status = build_portfolio_1d_aligned_closes(
                        closes_raw, ac_map
                    )
                    portfolio_1d = True
                else:
                    trim_mode = (
                        "last_24h"
                        if ac_filter == AssetClass.CRYPTO
                        else "rth_today_or_prior"
                    )
                    closes, session_status = trim_closes_map(
                        closes_raw, mode=trim_mode
                    )
            else:
                closes = densify_crypto_closes_map(closes_raw, ac_map)
            missing = [t for t in tickers if t not in closes or not closes[t]]
            mv_series, agg_meta = aggregate_mv_series_time_aware(
                timeline,
                closes,
                tickers=tickers,
                coverage_threshold=cov_threshold,
                # Grid path already full-book each bar; preseed still helps safety
                preseed_first_marks=portfolio_1d,
            )
            quantity_basis = str(
                agg_meta.get("quantity_basis") or "holdings_as_of_each_date"
            )
            note = (
                "Holdings as of each bar × historical prices (intraday 5m) · buy/sell markers."
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

        # Desk book MV (same formula as executive snapshot). Exposed in meta for UI.
        # Daily only: pin series tip to book so multi-day last matches desk.
        # 1D: never rewrite the path tip — that fakes a cliff vs Yahoo 5m bars.
        book_mv: Decimal | None = self._book_market_value_usd(
            lots, asset_class=ac_filter
        )
        if book_mv is None and qty_map:
            book_mv = self._book_mv_from_qty(qty_map)
        if not is_intraday and mv_series and book_mv is not None:
            mv_series = list(mv_series)
            last_ts = mv_series[-1][0]
            mv_series[-1] = (last_ts, _q2(book_mv))
        if is_intraday and book_mv is not None:
            note = (
                "Path from Yahoo 5m · desk book mark is the executive snapshot total "
                "(shown separately; not forced onto the last bar). "
            ) + note
        points = [{"date": d_ts, "value": _str_dec(v)} for d_ts, v in mv_series]
        first = mv_series[0][1] if mv_series else None
        last = mv_series[-1][1] if mv_series else None
        flows = window_external_flows(
            events,
            points,
            asset_class=ac_filter,
            asset_class_by_ticker=ac_map,
        )
        # Pure mark P&L on qty held at chart open (aligned to displayed series)
        chart_first_ts = mv_series[0][0] if mv_series else None
        chart_last_ts = mv_series[-1][0] if mv_series else None
        mark = window_mark_performance(
            timeline,
            closes,
            tickers=tickers,
            chart_first_ts=chart_first_ts,
            chart_last_ts=chart_last_ts,
        )
        ch = performance_change_meta(
            first,
            last,
            performance_abs=mark["performance_abs"],
            open_basis_usd=mark["open_basis_usd"],
            performance_pct=mark["performance_pct"],
            buys_usd=flows["buys_usd"],
            sells_usd=flows["sells_usd"],
            places=2,
        )
        window_components: dict[str, Any] | None = None
        # Portfolio: optional Stocks/Crypto legs (RTH vs 24h on 1D) — do NOT
        # override headline. Headline stays chart-series book Δ + same-series mark.
        if (
            ac_filter is None
            and quantity_basis.startswith("holdings_as_of")
            and closes_raw
        ):
            try:
                window_components = portfolio_window_from_components(
                    timeline,
                    closes_raw,
                    ac_map,
                    tickers,
                    is_intraday=is_intraday,
                    coverage_threshold=cov_threshold,
                    events=events,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("portfolio window components failed: %s", exc)
                window_components = None

        if quantity_basis.startswith("holdings_as_of"):
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
            note = (
                "Book change = chart endpoints · Mark P&L on qty at open · "
                "Net capital closes the gap. "
            ) + note
        elif is_intraday and session_status == "regular":
            note = "US regular session (5m). " + note
        elif is_intraday and len(mv_series) <= 3:
            note = f"Session open · {len(mv_series)} bar(s). " + note
        trades = collect_trade_markers(
            events,
            points,
            asset_class=ac_filter,
            asset_class_by_ticker=ac_map,
        )
        meta_out: dict[str, Any] = {
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
        }
        if book_mv is not None:
            meta_out["book_market_value_usd"] = _str_dec(book_mv)
            if last is not None:
                meta_out["book_vs_path_abs"] = _str_dec(last - book_mv)
        if window_components is not None:
            meta_out["window_components"] = window_components
        return HistoryResult(
            scope="all" if scope == "all" else "asset_class",
            label=label,
            range=range_norm,
            currency="USD",
            series_kind="market_value",
            interval=interval,
            as_of=ts,
            points=points,
            meta=meta_out,
        )

    def window_performance(
        self,
        *,
        range_key: RangeKey | str = "1y",
    ) -> dict[str, Any]:
        """
        Per open-ticker price performance over the same window as the live chart.
        """
        if not self.enabled:
            raise RuntimeError("yfinance disabled")

        period, interval, point_kind = range_to_yfinance_spec(str(range_key))
        range_norm = str(range_key).strip().lower()
        is_intraday = point_kind == "intraday"
        lots = self._open_lots()
        if not lots:
            return {
                "range": range_norm,
                "as_of": utc_now().isoformat(),
                "items": [],
            }

        tickers: list[str] = []
        ac_map: dict[str, str | None] = {}
        for lot in lots:
            t = lot.ticker.upper()
            if t not in ac_map:
                ac_map[t] = lot.asset_class.value if lot.asset_class else None
                tickers.append(t)
        tickers = sorted(set(tickers))

        closes = self._fetch_closes(tickers, ac_map, period, interval)
        items: list[dict[str, Any]] = []
        for t in tickers:
            ac = ac_map.get(t)
            series = closes.get(t) or []
            session_status = None
            if is_intraday and series:
                mode: Literal["rth_today_or_prior", "last_24h"] = (
                    "last_24h" if (ac or "").lower() == "crypto" else "rth_today_or_prior"
                )
                series, session_status = trim_intraday_series(series, mode=mode)
            places = 4 if (ac or "").lower() == "crypto" else 2
            if not series:
                items.append(
                    {
                        "ticker": t,
                        "asset_class": ac,
                        "first_value": None,
                        "last_value": None,
                        "change_pct": None,
                        "change_abs": None,
                        "currency": "USD",
                        "session_status": session_status,
                    }
                )
                continue
            first, last = series[0][1], series[-1][1]
            ch = _change_meta(first, last, places=places)
            items.append(
                {
                    "ticker": t,
                    "asset_class": ac,
                    "first_value": ch["first_value"],
                    "last_value": ch["last_value"],
                    "change_pct": ch["change_pct"],
                    "change_abs": ch["change_abs"],
                    "currency": "USD",
                    "session_status": session_status,
                }
            )

        # Best performers first; missing last
        items.sort(
            key=lambda x: (
                x["change_pct"] is None,
                -(x["change_pct"] if x["change_pct"] is not None else 0.0),
                x["ticker"],
            )
        )
        return {
            "range": range_norm,
            "as_of": utc_now().isoformat(),
            "items": items,
        }
