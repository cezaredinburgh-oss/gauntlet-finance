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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from backend.common.timeutil import local_midnight, resolve_day_timezone, resolve_zone, utc_now
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
# 1d uses 5d of 5m bars then trims to RTH / local calendar day — bare period=1d is empty/fragile at open.
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

SessionTag = Literal["pre", "rth", "ah", "prior_close", "local"]


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    """One tape print. ``session`` is set by 1D trim; raw fetch leaves it None."""

    ts: str
    px: Decimal
    session: SessionTag | None = None

    def __getitem__(self, i: int) -> str | Decimal:
        if i == 0:
            return self.ts
        if i == 1:
            return self.px
        raise IndexError(i)

    def __iter__(self) -> Iterator[str | Decimal]:
        yield self.ts
        yield self.px


def sp(
    ts: str,
    px: Decimal | str | int | float,
    session: SessionTag | None = None,
) -> SeriesPoint:
    """Test/helper constructor."""
    px_d = px if isinstance(px, Decimal) else Decimal(str(px))
    return SeriesPoint(ts=ts, px=px_d, session=session)


def _coerce_point(p: SeriesPoint | Sequence[Any]) -> SeriesPoint:
    if isinstance(p, SeriesPoint):
        return p
    ts = str(p[0])
    raw_px = p[1]
    px = raw_px if isinstance(raw_px, Decimal) else Decimal(str(raw_px))
    session = p[2] if len(p) > 2 else None  # type: ignore[misc]
    return SeriesPoint(ts=ts, px=px, session=session)


def _coerce_series(series: Sequence[Any] | None) -> list[SeriesPoint]:
    if not series:
        return []
    return [_coerce_point(p) for p in series]


def _serialize_point(p: SeriesPoint, places: int = 2) -> dict[str, str]:
    out: dict[str, str] = {"date": p.ts, "value": _str_dec(p.px, places)}
    if p.session is not None:
        out["session"] = p.session
    return out


# Process cache: key -> (fetched_monotonic, closes_by_our_ticker)
_HISTORY_CACHE: dict[str, tuple[float, dict[str, list[SeriesPoint]]]] = {}

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


def _et_zone() -> ZoneInfo:
    return ZoneInfo("America/New_York")


def _coerce_zone(zone: str | ZoneInfo | None) -> ZoneInfo:
    if isinstance(zone, ZoneInfo):
        return zone
    return resolve_zone(zone if isinstance(zone, str) else None)


def _to_et(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_et_zone())


def classify_us_session(ts: str) -> Literal["pre", "rth", "ah"] | None:
    """ET session bucket. Never call on a point already tagged ``prior_close``."""
    tet = _to_et(_parse_ts(ts))
    t = tet.hour * 60 + tet.minute
    if 4 * 60 <= t < 9 * 60 + 30:
        return "pre"
    if 9 * 60 + 30 <= t < 16 * 60:
        return "rth"
    if 16 * 60 <= t <= 20 * 60:
        return "ah"
    return None


def _is_weekend_et(dt_et: datetime) -> bool:
    return dt_et.weekday() >= 5


def _session_status_from_clock(now_et: datetime) -> str:
    """Displayed 1D status from the America/New_York clock (no yesterday envelope)."""
    if _is_weekend_et(now_et):
        return "prior_session"
    t = now_et.hour * 60 + now_et.minute
    if t < 4 * 60:
        return "overnight"
    if t < 9 * 60 + 30:
        return "pre_market"
    if t < 16 * 60:
        return "regular"
    return "after_hours"


def _tag_local(points: list[SeriesPoint]) -> list[SeriesPoint]:
    return [SeriesPoint(ts=p.ts, px=p.px, session="local") for p in points]


def _last_px_at_or_before(
    series: list[SeriesPoint], cutoff: datetime
) -> Decimal | None:
    """Last observed print with timestamp ≤ cutoff (aware-to-aware)."""
    best_px: Decimal | None = None
    best_ts: datetime | None = None
    for p in _coerce_series(series):
        tdt = _parse_ts(p.ts)
        if tdt <= cutoff and (best_ts is None or tdt > best_ts):
            best_ts = tdt
            best_px = p.px
    return best_px


def _seed_local_midnight(
    today: list[SeriesPoint],
    *,
    midnight: datetime,
    open_px: Decimal | None,
) -> list[SeriesPoint]:
    """Prepend observed midnight print when the first live bar is later."""
    today = _coerce_series(today)
    if open_px is None:
        return today
    if today and _parse_ts(today[0].ts) <= midnight:
        return today
    seed_ts = midnight.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return [SeriesPoint(seed_ts, open_px), *today]


def _trim_local_day_or_prior(
    series: list[SeriesPoint],
    *,
    now: datetime,
    zone: ZoneInfo,
) -> tuple[list[SeriesPoint], str]:
    series = _coerce_series(series)
    midnight = local_midnight(now, zone)
    today = [p for p in series if _parse_ts(p.ts) >= midnight]
    today.sort(key=lambda p: _parse_ts(p.ts))
    open_px = _last_px_at_or_before(series, midnight)

    if today:
        return _tag_local(
            _seed_local_midnight(today, midnight=midnight, open_px=open_px)
        ), "local_day"

    by_day: dict[date, list[SeriesPoint]] = {}
    for p in series:
        local_d = _parse_ts(p.ts).astimezone(zone).date()
        if local_d < midnight.date():
            by_day.setdefault(local_d, []).append(p)
    if not by_day:
        return _tag_local(series[-min(12, len(series)) :]), "prior_local_day"

    last_day = max(by_day.keys())
    midnight = datetime(last_day.year, last_day.month, last_day.day, tzinfo=zone)
    next_d = last_day + timedelta(days=1)
    next_midnight = datetime(next_d.year, next_d.month, next_d.day, tzinfo=zone)
    today = [p for p in series if midnight <= _parse_ts(p.ts) < next_midnight]
    today.sort(key=lambda p: _parse_ts(p.ts))
    open_px = _last_px_at_or_before(series, midnight)
    if not today:
        return _tag_local(series[-min(12, len(series)) :]), "prior_local_day"
    return (
        _tag_local(_seed_local_midnight(today, midnight=midnight, open_px=open_px)),
        "prior_local_day",
    )


def _prior_rth_point(
    series: list[SeriesPoint],
    *,
    before: datetime,
) -> SeriesPoint | None:
    """Last 5m RTH print (09:30 ≤ ET < 16:00) strictly before ``before``."""
    best: SeriesPoint | None = None
    best_ts: datetime | None = None
    for p in _coerce_series(series):
        tdt = _parse_ts(p.ts)
        if tdt.tzinfo is None:
            tdt = tdt.replace(tzinfo=timezone.utc)
        if tdt >= before:
            continue
        if classify_us_session(p.ts) != "rth":
            continue
        if best_ts is None or tdt > best_ts:
            best_ts = tdt
            best = p
    if best is None:
        return None
    return SeriesPoint(ts=best.ts, px=best.px, session="prior_close")


def _trim_us_extended(
    series: list[SeriesPoint],
    *,
    now: datetime,
) -> tuple[list[SeriesPoint], str]:
    """
    Stock/ETF 1D envelope: prior-close seed + today's pre/rth/ah.

    Any now_et < 09:30 (incl. 00:00–03:59 and weekends) keeps zero yesterday RTH
    vertices besides the single ``prior_close`` seed.
    """
    series = _coerce_series(series)
    now_et = _to_et(now)
    status = _session_status_from_clock(now_et)
    displayed = now_et.date()
    session_open = datetime(
        displayed.year, displayed.month, displayed.day, 9, 30, tzinfo=_et_zone()
    )

    live: list[SeriesPoint] = []
    if status != "prior_session":
        for p in series:
            tdt = _parse_ts(p.ts)
            if tdt.tzinfo is None:
                tdt = tdt.replace(tzinfo=timezone.utc)
            if tdt > now:
                continue
            sess = classify_us_session(p.ts)
            if sess is None:
                continue
            tet = _to_et(tdt)
            if tet.date() != displayed:
                continue
            live.append(SeriesPoint(ts=p.ts, px=p.px, session=sess))
        live.sort(key=lambda p: _parse_ts(p.ts))

    seed = _prior_rth_point(series, before=session_open)
    out: list[SeriesPoint] = []
    if seed is not None:
        if live and live[0].ts == seed.ts:
            live = live[1:]
        out.append(seed)
    out.extend(live)
    if not out:
        return [], "empty"
    return out, status


def trim_intraday_series(
    series: list[SeriesPoint],
    *,
    mode: Literal["rth_today_or_prior", "local_day_or_prior"],
    now: datetime | None = None,
    zone: ZoneInfo | None = None,
) -> tuple[list[SeriesPoint], str]:
    """
    Trim 5m bars for 1D display.

    rth_today_or_prior — US extended envelope (seed + today pre/rth/ah).
    local_day_or_prior — local calendar day from midnight; if none yet, prior day.
    """
    series = _coerce_series(series)
    if not series:
        return [], "empty"

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if mode == "local_day_or_prior":
        return _trim_local_day_or_prior(
            series, now=now, zone=zone or resolve_zone(None)
        )

    return _trim_us_extended(series, now=now)


def trim_closes_map(
    closes: dict[str, list[SeriesPoint]],
    *,
    mode: Literal["rth_today_or_prior", "local_day_or_prior"],
    now: datetime | None = None,
    zone: ZoneInfo | None = None,
) -> tuple[dict[str, list[SeriesPoint]], str]:
    """Trim each ticker; session_status ranks extended statuses over prior."""
    out: dict[str, list[SeriesPoint]] = {}
    statuses: list[str] = []
    for t, series in closes.items():
        trimmed, st = trim_intraday_series(series, mode=mode, now=now, zone=zone)
        if trimmed:
            out[t] = trimmed
            statuses.append(st)
    if not statuses:
        return {}, "empty"
    if any(s == "regular" for s in statuses):
        status = "regular"
    elif any(s == "after_hours" for s in statuses):
        status = "after_hours"
    elif any(s == "pre_market" for s in statuses):
        status = "pre_market"
    elif any(s == "overnight" for s in statuses):
        status = "overnight"
    elif any(s == "local_day" for s in statuses):
        status = "local_day"
    elif any(s == "prior_local_day" for s in statuses):
        status = "prior_local_day"
    else:
        status = "prior_session"
    return out, status


def _prior_rth_close(
    series: list[SeriesPoint],
    *,
    before: datetime,
) -> Decimal | None:
    """Last US RTH close strictly before ``before`` (for overnight carry)."""
    pt = _prior_rth_point(series, before=before)
    return pt.px if pt is not None else None


def rth_only(series: list[SeriesPoint]) -> list[SeriesPoint]:
    """Keep RTH prints only (09:30 ≤ ET < 16:00). Used inside the mixed 1D grid."""
    out: list[SeriesPoint] = []
    for p in _coerce_series(series):
        sess = p.session if p.session is not None else classify_us_session(p.ts)
        if sess == "rth":
            out.append(SeriesPoint(ts=p.ts, px=p.px, session="rth"))
    return out


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
    for p in _coerce_series(series):
        tdt = _parse_ts(p.ts)
        if tdt.tzinfo is None:
            tdt = tdt.replace(tzinfo=timezone.utc)
        else:
            tdt = tdt.astimezone(timezone.utc)
        pairs.append((tdt, p.px))
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


def _utc_5m_grid(window_open: datetime, window_end: datetime) -> list[datetime]:
    grid: list[datetime] = []
    t = window_open
    while t <= window_end:
        grid.append(t)
        t += timedelta(minutes=5)
    return grid


def _align_closes_on_grid(
    closes_full: dict[str, list[SeriesPoint]],
    asset_classes: dict[str, str | None],
    grid: list[datetime],
    window_open: datetime,
) -> dict[str, list[SeriesPoint]]:
    out: dict[str, list[SeriesPoint]] = {}
    for ticker, full in closes_full.items():
        if not full:
            continue
        ac = (asset_classes.get(ticker) or "").lower()
        is_crypto = ac == "crypto"
        full_pts = _coerce_series(full)
        live_src = full_pts if is_crypto else rth_only(full_pts)
        pairs = _series_to_sorted_pairs(live_src)
        if is_crypto and not pairs:
            continue

        if is_crypto:
            open_px, _ = _px_asof(pairs, window_open)
            if open_px is None:
                for pdt, px in pairs:
                    if pdt >= window_open:
                        open_px = px
                        break
            if open_px is None:
                open_px = pairs[0][1]
        else:
            open_px = _prior_rth_close(full_pts, before=window_open)
            if open_px is None:
                open_px, _ = _px_asof(pairs, window_open) if pairs else (None, 0)
            if open_px is None and pairs:
                open_px = pairs[0][1]
            if open_px is None:
                continue

        series_out: list[SeriesPoint] = []
        last_px = open_px
        hint = 0
        for g in grid:
            live, hint = _px_asof(pairs, g, start_i=hint)
            if live is not None:
                last_px = live
            series_out.append(
                SeriesPoint(g.replace(microsecond=0).isoformat(), last_px)
            )
        out[ticker] = series_out
    return out


def build_portfolio_1d_aligned_closes(
    closes_full: dict[str, list[SeriesPoint]],
    asset_classes: dict[str, str | None],
    *,
    now: datetime | None = None,
    zone: ZoneInfo | None = None,
) -> tuple[dict[str, list[SeriesPoint]], str]:
    """
    Portfolio 1D on a **shared 5m UTC grid** from local midnight to now.

    Every ticker gets a mark on every grid timestamp (forward-filled):
      - Equity: previous RTH close until the first live RTH bar, then live
      - Crypto: last print ≤ window open, then live 5m

    Same timestamps → additive window Δ = stocks session + crypto local day.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    zone = zone or resolve_zone(None)
    midnight = local_midnight(now, zone)
    window_end = _snap_down_5m(now)
    window_open = _snap_down_5m(midnight)
    grid = _utc_5m_grid(window_open, window_end)
    if not grid:
        return {}, "empty"

    out = _align_closes_on_grid(closes_full, asset_classes, grid, window_open)
    if not out:
        return {}, "empty"
    # Any print produces a carry-forward grid (not an empty book). A second
    # pass to prior midnight cannot invent data and would span ~48h to now.
    return out, "local_day"


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
        series.append(SeriesPoint(ts, px))
    return series


def _yfinance_history_batch(
    yahoo_symbols: list[str],
    yahoo_to_our: dict[str, str],
    period: str,
    interval: str,
    *,
    prepost: bool = False,
) -> dict[str, list[SeriesPoint]]:
    """Fetch closes; keys are our tickers. ``prepost`` is production-only (tests never pass it)."""
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
            prepost=prepost,
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
            # Per-ticker fallback only when the whole batch frame is empty.
            # Sequential Ticker.history for every missing name was a major
            # latency/timeout source under soft-refresh thrash.
            if not series and data is None:
                t = yf.Ticker(ysym)
                hist = t.history(
                    period=period,
                    interval=interval,
                    auto_adjust=True,
                    prepost=prepost,
                )
                if hist is not None and not hist.empty:
                    hclose = hist["Close"] if "Close" in hist.columns else None
                    series = _series_from_close(hclose, intraday=intraday)
        except Exception as exc:  # noqa: BLE001
            logger.warning("history failed for %s: %s", ysym, exc)
            continue
        if series:
            series.sort(key=lambda x: x.ts)
            out[our] = series
    if prepost:
        logger.debug(
            "equity 5m prepost=True symbols=%s bars=%s",
            len(yahoo_symbols),
            sum(len(s) for s in out.values()),
        )
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
    session_maps: dict[str, dict[str, SessionTag | None]] = {}
    first_bar: dict[str, str] = {}
    latest_px: dict[str, Decimal] = {}
    all_ts: set[str] = set()
    for t, series in closes_by_ticker.items():
        if t not in qty_by_ticker:
            continue
        m: dict[str, Decimal] = {}
        sm: dict[str, SessionTag | None] = {}
        for p in _coerce_series(series):
            m[p.ts] = p.px
            sm[p.ts] = p.session
            all_ts.add(p.ts)
        if m:
            price_maps[t] = m
            session_maps[t] = sm
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
        at_ts = [
            session_maps[t][ts]
            for t, sm in session_maps.items()
            if ts in sm
        ]
        if at_ts and all(s == "prior_close" for s in at_ts):
            sess: SessionTag | None = "prior_close"
        elif "T" in ts:
            sess = classify_us_session(ts)
        else:
            sess = None
        result.append(SeriesPoint(ts, _q2(total), sess))

    series_start = result[0].ts if result else None
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
    series = _coerce_series(series)
    if len(series) < 2:
        return series
    if any("T" in p.ts for p in series):
        return series
    # Sort by date
    ordered = sorted(series, key=lambda p: p.ts[:10])
    out: list[SeriesPoint] = [ordered[0]]
    for i in range(1, len(ordered)):
        prev = out[-1]
        cur = ordered[i]
        try:
            prev_d = date.fromisoformat(prev.ts[:10])
            cur_d = date.fromisoformat(cur.ts[:10])
        except ValueError:
            out.append(SeriesPoint(cur.ts[:10], cur.px, cur.session))
            continue
        gap = (cur_d - prev_d).days
        if 1 < gap <= max_gap_days:
            d = prev_d + timedelta(days=1)
            while d < cur_d:
                out.append(SeriesPoint(d.isoformat(), prev.px, prev.session))
                d += timedelta(days=1)
        out.append(SeriesPoint(cur.ts[:10], cur.px, cur.session))
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
    series = _coerce_series(series)
    as_of = _parse_ts(as_of_ts)
    best: Decimal | None = None
    for p in sorted(series, key=lambda x: _parse_ts(x.ts)):
        if _parse_ts(p.ts) <= as_of:
            try:
                best = p.px if isinstance(p.px, Decimal) else Decimal(str(p.px))
            except Exception:  # noqa: BLE001
                continue
        else:
            break
    if best is not None:
        return best
    # Before first print: use first available (still gate qty separately)
    try:
        ordered = sorted(series, key=lambda x: _parse_ts(x.ts))
        px = ordered[0].px
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
            for p in _coerce_series(series):
                all_ts.append(p.ts)
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
    session_maps: dict[str, dict[str, SessionTag | None]] = {}
    first_bar: dict[str, str] = {}
    first_px: dict[str, Decimal] = {}
    latest_px: dict[str, Decimal] = {}
    all_ts: set[str] = set()
    for t in universe:
        series = _coerce_series(closes_by_ticker.get(t) or [])
        if not series:
            continue
        m: dict[str, Decimal] = {}
        sm: dict[str, SessionTag | None] = {}
        for p in series:
            m[p.ts] = p.px
            sm[p.ts] = p.session
            all_ts.add(p.ts)
        if not m:
            continue
        price_maps[t] = m
        session_maps[t] = sm
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
        at_ts = [
            session_maps[t][ts]
            for t, sm in session_maps.items()
            if ts in sm
        ]
        if at_ts and all(s == "prior_close" for s in at_ts):
            sess: SessionTag | None = "prior_close"
        elif "T" in ts:
            sess = classify_us_session(ts)
        else:
            sess = None
        result.append(SeriesPoint(ts, _q2(total_mv), sess))

    series_start = result[0].ts if result else None
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
    first, last = series[0].px, series[-1].px
    return first, last, last - first


def _split_closes_by_class(
    closes: dict[str, list[SeriesPoint]],
    ac_map: dict[str, str | None],
) -> tuple[dict[str, list[SeriesPoint]], dict[str, list[SeriesPoint]]]:
    stock_closes: dict[str, list[SeriesPoint]] = {}
    crypto_closes: dict[str, list[SeriesPoint]] = {}
    for t, series in closes.items():
        if (ac_map.get(t) or "").lower() == "crypto":
            crypto_closes[t] = series
        else:
            stock_closes[t] = series
    return stock_closes, crypto_closes


def portfolio_window_from_components(
    timeline: HoldingsTimeline,
    closes_raw: dict[str, list[SeriesPoint]],
    ac_map: dict[str, str | None],
    tickers: list[str],
    *,
    is_intraday: bool,
    coverage_threshold: Decimal,
    events: list[InvestmentEvent] | None = None,
    now: datetime | None = None,
    zone: ZoneInfo | None = None,
) -> dict[str, Any]:
    """
    Portfolio window **performance** = Stocks leg + Crypto leg.

    On 1D, both legs are sliced from the shared midnight grid (same timestamps).
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

    used_aligned_grid = False
    if is_intraday:
        aligned, _status = build_portfolio_1d_aligned_closes(
            closes_raw, ac_map, now=now, zone=zone
        )
        if aligned:
            stock_closes, crypto_closes = _split_closes_by_class(aligned, ac_map)
            used_aligned_grid = True
        else:
            # Do not run extended rth_today_or_prior on mixed-book raw series.
            stock_closes, crypto_closes = {}, {}
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
            for p in _coerce_series(series):
                ts_all.append(p.ts)
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
        pts = [{"date": p.ts, "value": str(p.px)} for p in _coerce_series(best)]
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
            "stocks_rth_plus_crypto_local_day_mark"
            if used_aligned_grid
            else (
                "stocks_rth_plus_crypto_local_day_independent"
                if is_intraday
                else "stocks_plus_crypto_mark_same_range"
            )
        ),
        "change_basis": "mark_performance_start_qty",
    }


def _day_change_from_series(series: list[SeriesPoint], *, places: int = 2) -> dict[str, Any]:
    series = _coerce_series(series)
    if not series:
        return {
            "day_open": None,
            "day_last": None,
            "day_change_pct": None,
            "day_change_abs": None,
        }
    first, last = series[0].px, series[-1].px
    abs_ch = last - first
    pct = float((abs_ch / first) * 100) if first != 0 else None
    rth_open = next((p.px for p in series if p.session == "rth"), None)
    tagged = any(p.session in ("pre", "rth", "ah", "prior_close") for p in series)
    day_open_px = rth_open if tagged else first
    return {
        "day_open": _str_dec(day_open_px, places) if day_open_px is not None else None,
        "day_last": _str_dec(last, places),
        "day_change_pct": round(pct, 2) if pct is not None else None,
        "day_change_abs": _str_dec(abs_ch, places),
    }


def _null_extended_fields() -> dict[str, Any]:
    return {
        "prior_close": None,
        "change_since_close_abs": None,
        "change_since_close_pct": None,
        "change_rth_abs": None,
        "change_rth_pct": None,
        "pnl_rth_usd": None,
        "rth_last": None,
    }


def extended_change_meta(
    series: list[SeriesPoint],
    *,
    qty: Decimal | None = None,
    places: int = 4,
) -> dict[str, Any]:
    """
    Stock 1D vs-close primary + RTH pair.

    Primary Δ: (1) last − prior RTH last (5m), (2) last − first plotted, (3) null.
    Fallback (2) is vs 09:30 when the 5d tape has no prior RTH.
    """
    series = _coerce_series(series)
    empty = {
        "first_value": None,
        "last_value": None,
        "change_abs": None,
        "change_pct": None,
        "day_open": None,
        "day_last": None,
        "day_change_abs": None,
        "day_change_pct": None,
        "pnl_usd": None,
        **_null_extended_fields(),
    }
    if not series:
        return empty

    first_px = series[0].px
    last_any = series[-1].px
    prior_close_px: Decimal | None = None
    for p in series:
        if p.session == "prior_close":
            prior_close_px = p.px
            break
    rth_pts = [p for p in series if p.session == "rth"]
    rth_open = rth_pts[0].px if rth_pts else None
    last_rth = rth_pts[-1].px if rth_pts else None

    change_abs: Decimal | None = None
    denom: Decimal | None = None
    if last_any is not None and prior_close_px is not None:
        change_abs = last_any - prior_close_px
        denom = prior_close_px
    elif last_any is not None and first_px is not None:
        change_abs = last_any - first_px
        denom = first_px

    change_pct = None
    if change_abs is not None and denom is not None and denom != 0:
        change_pct = float((change_abs / denom) * 100)

    change_rth_abs = (
        last_rth - rth_open if last_rth is not None and rth_open is not None else None
    )
    change_rth_pct = None
    if change_rth_abs is not None and rth_open is not None and rth_open != 0:
        change_rth_pct = float((change_rth_abs / rth_open) * 100)

    pnl = qty * change_abs if qty is not None and change_abs is not None else None
    pnl_rth = (
        qty * change_rth_abs if qty is not None and change_rth_abs is not None else None
    )
    pct_r = round(change_pct, 2) if change_pct is not None else None
    return {
        "first_value": _str_dec(first_px, places),
        "last_value": _str_dec(last_any, places),
        "change_abs": _str_dec(change_abs, places) if change_abs is not None else None,
        "change_pct": pct_r,
        "change_since_close_abs": (
            _str_dec(change_abs, places) if change_abs is not None else None
        ),
        "change_since_close_pct": pct_r,
        "prior_close": (
            _str_dec(prior_close_px, places) if prior_close_px is not None else None
        ),
        "day_open": _str_dec(rth_open, places) if rth_open is not None else None,
        "rth_last": _str_dec(last_rth, places) if last_rth is not None else None,
        "change_rth_abs": (
            _str_dec(change_rth_abs, places) if change_rth_abs is not None else None
        ),
        "change_rth_pct": round(change_rth_pct, 2) if change_rth_pct is not None else None,
        "pnl_usd": _str_dec(pnl, 2) if pnl is not None else None,
        "pnl_rth_usd": _str_dec(pnl_rth, 2) if pnl_rth is not None else None,
        "day_last": _str_dec(last_any, places),
        "day_change_abs": _str_dec(change_abs, places) if change_abs is not None else None,
        "day_change_pct": pct_r,
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
        """Latest Prices-tab USD marks keyed by ticker (one Sheets list per call)."""
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

    def _book_price_usd(
        self, ticker: str, prices: dict[str, Decimal] | None = None
    ) -> Decimal | None:
        m = prices if prices is not None else self._book_prices_usd()
        return m.get(ticker.strip().upper())

    def _book_mv_from_qty(
        self,
        qty_map: dict[str, Decimal],
        prices: dict[str, Decimal] | None = None,
    ) -> Decimal | None:
        px_map = prices if prices is not None else self._book_prices_usd()
        if not qty_map or not px_map:
            return None
        total = Decimal("0")
        any_priced = False
        for t, qty in qty_map.items():
            px = px_map.get(t.upper())
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
        prices: dict[str, Decimal] | None = None,
    ) -> Decimal | None:
        px_map = prices if prices is not None else self._book_prices_usd()
        if not px_map:
            return None
        total = Decimal("0")
        any_priced = False
        for lot in open_lots:
            t = lot.ticker.upper()
            if asset_class is not None:
                if lot.asset_class is None or lot.asset_class != asset_class:
                    continue
            px = px_map.get(t)
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
            f"{period}|{interval}|{session_tag}|extended_v1|"
            f"{'|'.join(sorted(yahoo_symbols))}"
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
            prepost = interval == "5m" and group is equity_syms
            if self._fetcher is _yfinance_history_batch:
                part = _yfinance_history_batch(
                    group, sub_map, period, interval, prepost=prepost
                )
            else:
                part = self._fetcher(group, sub_map, period, interval)
            payload.update({k: _coerce_series(v) for k, v in part.items()})

        # Don't pin empty / near-empty intraday results for full TTL (open-flash)
        max_len = max((len(s) for s in payload.values()), default=0)
        if is_intraday and max_len < 3:
            # Short negative cache only
            _HISTORY_CACHE[cache_key] = (time.monotonic() - max(0, ttl - 15), payload)
        else:
            _HISTORY_CACHE[cache_key] = (time.monotonic(), payload)
        return payload

    def _resolve_zone_arg(self, zone: str | ZoneInfo | None) -> ZoneInfo:
        if zone is None:
            return resolve_zone(resolve_day_timezone(self.repo))
        return _coerce_zone(zone)

    def _mark_at(
        self,
        ticker: str,
        ac: str | None,
        asof: datetime,
        *,
        crypto_5m: dict[str, list[SeriesPoint]],
        stock_daily: dict[str, list[SeriesPoint]],
    ) -> Decimal | None:
        if (ac or "").lower() == "crypto":
            pairs = _series_to_sorted_pairs(crypto_5m.get(ticker, []))
            px, _ = _px_asof(pairs, asof)
            return px
        series = stock_daily.get(ticker, [])
        pairs = _series_to_sorted_pairs(series)
        px, _ = _px_asof(pairs, asof)
        if px is None:
            px = _prior_rth_close(series, before=asof)
        return px

    def _day_change_from_marks(
        self,
        qty_map: dict[str, Decimal],
        ac_map: dict[str, str | None],
        *,
        t_open: datetime,
        t_last: datetime,
        crypto_5m: dict[str, list[SeriesPoint]],
        stock_daily: dict[str, list[SeriesPoint]],
        places: int,
    ) -> dict[str, Any]:
        open_mv = Decimal("0")
        last_mv = Decimal("0")
        any_open = False
        any_last = False
        for t, qty in qty_map.items():
            if qty <= 0:
                continue
            ac = ac_map.get(t)
            open_px = self._mark_at(
                t, ac, t_open, crypto_5m=crypto_5m, stock_daily=stock_daily
            )
            last_px = self._mark_at(
                t, ac, t_last, crypto_5m=crypto_5m, stock_daily=stock_daily
            )
            if open_px is not None:
                open_mv += qty * open_px
                any_open = True
            if last_px is not None:
                last_mv += qty * last_px
                any_last = True
        if not any_open and not any_last:
            return _day_change_from_series([], places=places)
        first = _q2(open_mv) if places == 2 else open_mv
        last = _q2(last_mv) if places == 2 else last_mv
        series: list[SeriesPoint] = []
        if any_open:
            series.append(SeriesPoint(t_open.isoformat(), first))
        if any_last:
            series.append(SeriesPoint(t_last.isoformat(), last))
        return _day_change_from_series(series, places=places)

    def _resolve_day_change(
        self,
        qty_map: dict[str, Decimal],
        ac_map: dict[str, str | None],
        *,
        series_kind: str,
        main_range: str,
        main_series: list[SeriesPoint] | None = None,
        places: int = 2,
        now: datetime | None = None,
        zone: ZoneInfo | None = None,
    ) -> dict[str, Any]:
        """Day open→last change. 1D uses the already-trimmed series (seed included)."""
        try:
            if main_range == "1d" and main_series is not None:
                return _day_change_from_series(main_series, places=places)

            now = now or datetime.now(timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            zone = zone or resolve_zone(None)

            tickers = sorted(qty_map.keys())
            crypto_names = [
                t for t in tickers if (ac_map.get(t) or "").lower() == "crypto"
            ]
            stock_names = [
                t for t in tickers if (ac_map.get(t) or "").lower() != "crypto"
            ]
            has_crypto = bool(crypto_names)
            all_crypto = bool(tickers) and not stock_names

            if not has_crypto:
                if main_series is not None and len(main_series) >= 2:
                    return _day_change_from_series(main_series[-2:], places=places)
                if not tickers:
                    return _day_change_from_series([], places=places)
                closes = self._fetch_closes(tickers, ac_map, "5d", "1d")
                if series_kind == "price":
                    return _day_change_from_series(
                        closes.get(tickers[0], []), places=places
                    )
                mv, _agg_meta = aggregate_mv_series(qty_map, closes)
                return _day_change_from_series(mv, places=places)

            crypto_5m = (
                self._fetch_closes(crypto_names, ac_map, "5d", "5m")
                if crypto_names
                else {}
            )

            if all_crypto and series_kind == "price":
                t = tickers[0]
                trimmed, _st = trim_intraday_series(
                    crypto_5m.get(t, []),
                    mode="local_day_or_prior",
                    now=now,
                    zone=zone,
                )
                return _day_change_from_series(trimmed, places=places)

            _, crypto_status = trim_closes_map(
                crypto_5m, mode="local_day_or_prior", now=now, zone=zone
            )
            t_open = local_midnight(now, zone)
            if crypto_status == "prior_local_day":
                t_open = local_midnight(t_open - timedelta(seconds=1), zone)
            stock_daily = (
                self._fetch_closes(stock_names, ac_map, "5d", "1d")
                if stock_names
                else {}
            )
            if all_crypto:
                # Crypto-only MV: same T_open marks (seeded local day) × qty
                return self._day_change_from_marks(
                    qty_map,
                    ac_map,
                    t_open=t_open,
                    t_last=now,
                    crypto_5m=crypto_5m,
                    stock_daily={},
                    places=places,
                )
            # Last two daily MV bars are UTC-ish dates, not local midnight.
            return self._day_change_from_marks(
                qty_map,
                ac_map,
                t_open=t_open,
                t_last=now,
                crypto_5m=crypto_5m,
                stock_daily=stock_daily,
                places=places,
            )
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
        zone: str | ZoneInfo | None = None,
        now: datetime | None = None,
    ) -> HistoryResult:
        if not self.enabled:
            raise RuntimeError("yfinance disabled")

        period, interval, point_kind = range_to_yfinance_spec(str(range_key))
        range_norm = str(range_key).strip().lower()
        lots = self._open_lots()
        ts = now or utc_now()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        zone_info = self._resolve_zone_arg(zone)
        zone_key = zone_info.key
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
            ac = (ac_map.get(t) or "").lower()
            day_mode: Literal["rth_today_or_prior", "local_day_or_prior"] = (
                "local_day_or_prior" if ac == "crypto" else "rth_today_or_prior"
            )
            if is_intraday:
                closes, session_status = trim_closes_map(
                    closes, mode=day_mode, now=ts, zone=zone_info
                )
            elif (ac_map.get(t) or "").lower() == "crypto":
                closes = densify_crypto_closes_map(closes, ac_map)
            series = closes.get(t, [])
            missing = [] if series else [t]
            qty = qty_map[t]
            avg_cost = (cost / qty) if qty > 0 else None
            book_prices = self._book_prices_usd()
            # Desk quote for UI parity (never rewrite 1D path — that fakes a cliff).
            # Daily ranges only: pin tip to book so multi-day "last" matches desk.
            book_px = self._book_price_usd(t, book_prices)
            if (
                not is_intraday
                and book_px is not None
                and series
            ):
                series = list(series)
                series[-1] = replace(series[-1], px=book_px)
            series = _coerce_series(series)
            points = [_serialize_point(p, places) for p in series]
            first = series[0].px if series else None
            last = series[-1].px if series else None
            stock_1d = is_intraday and ac != "crypto"
            if stock_1d:
                ch = extended_change_meta(series, qty=qty, places=4)
                day = {
                    "day_open": ch["day_open"],
                    "day_last": ch["day_last"],
                    "day_change_pct": ch["day_change_pct"],
                    "day_change_abs": ch["day_change_abs"],
                }
            else:
                ch = {
                    **_change_meta(first, last, places=places),
                    **_null_extended_fields(),
                }
                day = self._resolve_day_change(
                    qty_map,
                    ac_map,
                    series_kind="price",
                    main_range=range_norm,
                    main_series=series,
                    places=places,
                    now=ts,
                    zone=zone_info,
                )
            ysym = _normalize_yahoo_symbol(t, ac_map.get(t))
            note = (
                "Intraday (5m) USD path from Yahoo · desk mark is separate (Prices tab)."
                if point_kind == "intraday"
                else "Daily close (USD). Avg cost from open lots · buy/sell markers."
            )
            if is_intraday and session_status == "overnight":
                note = "Overnight · prior RTH last (5m). " + note
            elif is_intraday and session_status == "pre_market":
                n_pre = sum(1 for p in series if p.session == "pre")
                note = (
                    f"Pre-market · {n_pre} bar(s) since prior RTH last. " + note
                    if n_pre
                    else "Pre-market · no Yahoo prints yet. " + note
                )
            elif is_intraday and session_status == "after_hours":
                note = "After-hours · Yahoo 5m path (not desk book). " + note
            elif is_intraday and session_status == "prior_session":
                note = "Prior session · market closed. " + note
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
                "day_policy": {
                    "timezone": zone_key,
                    "mode": day_mode,
                    "session_status": session_status if is_intraday else None,
                },
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
                        closes_raw, ac_map, now=ts, zone=zone_info
                    )
                    portfolio_1d = True
                else:
                    trim_mode: Literal["rth_today_or_prior", "local_day_or_prior"] = (
                        "local_day_or_prior"
                        if ac_filter == AssetClass.CRYPTO
                        else "rth_today_or_prior"
                    )
                    closes, session_status = trim_closes_map(
                        closes_raw, mode=trim_mode, now=ts, zone=zone_info
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
                        closes_raw, ac_map, now=ts, zone=zone_info
                    )
                    portfolio_1d = True
                else:
                    trim_mode = (
                        "local_day_or_prior"
                        if ac_filter == AssetClass.CRYPTO
                        else "rth_today_or_prior"
                    )
                    closes, session_status = trim_closes_map(
                        closes_raw, mode=trim_mode, now=ts, zone=zone_info
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
        book_prices = self._book_prices_usd()
        book_mv: Decimal | None = self._book_market_value_usd(
            lots, asset_class=ac_filter, prices=book_prices
        )
        if book_mv is None and qty_map:
            book_mv = self._book_mv_from_qty(qty_map, book_prices)
        if not is_intraday and mv_series and book_mv is not None:
            mv_series = list(mv_series)
            mv_series[-1] = replace(mv_series[-1], px=_q2(book_mv))
        if is_intraday and book_mv is not None:
            note = (
                "Path from Yahoo 5m · desk book mark is the executive snapshot total "
                "(shown separately; not forced onto the last bar). "
            ) + note
        mv_series = _coerce_series(mv_series)
        # scope=all 1D stays untagged at book level (grid has no session).
        if ac_filter is None and is_intraday:
            points = [{"date": p.ts, "value": _str_dec(p.px, 2)} for p in mv_series]
        else:
            points = [_serialize_point(p, 2) for p in mv_series]
        first = mv_series[0].px if mv_series else None
        last = mv_series[-1].px if mv_series else None
        flows = window_external_flows(
            events,
            points,
            asset_class=ac_filter,
            asset_class_by_ticker=ac_map,
        )
        # Pure mark P&L on qty held at chart open (aligned to displayed series)
        chart_first_ts = mv_series[0].ts if mv_series else None
        chart_last_ts = mv_series[-1].ts if mv_series else None
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
        # Midnight-grid legs on 1D; do not override the headline.
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
                    now=ts,
                    zone=zone_info,
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
                main_series=mv_series,
                places=2,
                now=ts,
                zone=zone_info,
            )
        else:
            day = self._resolve_day_change(
                qty_map,
                ac_map,
                series_kind="market_value",
                main_range=range_norm,
                main_series=mv_series,
                places=2,
                now=ts,
                zone=zone_info,
            )
        short = agg_meta.get("short_history_tickers") or []
        if short:
            bits = [f"{s['ticker']} from {s['first_bar']}" for s in short[:8]]
            note += " Late listings: " + ", ".join(bits)
            if len(short) > 8:
                note += "…"
        if is_intraday and session_status == "overnight":
            note = "Overnight · prior RTH last (5m). " + note
        elif is_intraday and session_status == "pre_market":
            note = "Pre-market · Yahoo 5m path (not desk book). " + note
        elif is_intraday and session_status == "after_hours":
            note = "After-hours · Yahoo 5m path (not desk book). " + note
        elif is_intraday and session_status == "prior_session":
            note = "Prior session · market closed. " + note
        elif is_intraday and session_status == "prior_local_day":
            note = "Prior local day (today’s midnight not in Yahoo yet). " + note
        elif is_intraday and session_status == "local_day":
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
        if ac_filter == AssetClass.STOCK:
            book_day_mode = "rth_today_or_prior"
        else:
            book_day_mode = "local_day_or_prior"
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
            "day_policy": {
                "timezone": zone_key,
                "mode": book_day_mode,
                "session_status": session_status if is_intraday else None,
            },
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
        zone: str | ZoneInfo | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Per open-ticker price performance over the same window as the live chart.
        """
        if not self.enabled:
            raise RuntimeError("yfinance disabled")

        period, interval, point_kind = range_to_yfinance_spec(str(range_key))
        range_norm = str(range_key).strip().lower()
        is_intraday = point_kind == "intraday"
        ts = now or utc_now()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        zone_info = self._resolve_zone_arg(zone)
        lots = self._open_lots()
        if not lots:
            return {
                "range": range_norm,
                "as_of": ts.isoformat(),
                "items": [],
            }

        qty_map, _cost, ac_from_lots = self._qty_and_cost_by_ticker(
            lots, all_open=True
        )
        tickers: list[str] = []
        ac_map: dict[str, str | None] = {}
        for lot in lots:
            t = lot.ticker.upper()
            if t not in ac_map:
                ac_map[t] = lot.asset_class.value if lot.asset_class else None
                tickers.append(t)
        tickers = sorted(set(tickers))
        for t, ac in ac_from_lots.items():
            if ac_map.get(t) is None:
                ac_map[t] = ac

        closes = self._fetch_closes(tickers, ac_map, period, interval)
        items: list[dict[str, Any]] = []
        for t in tickers:
            ac = ac_map.get(t)
            is_crypto = (ac or "").lower() == "crypto"
            series = closes.get(t) or []
            session_status = None
            if is_intraday and series:
                mode: Literal["rth_today_or_prior", "local_day_or_prior"] = (
                    "local_day_or_prior" if is_crypto else "rth_today_or_prior"
                )
                series, session_status = trim_intraday_series(
                    series, mode=mode, now=ts, zone=zone_info
                )
            qty = qty_map.get(t, Decimal("0"))
            stock_1d = is_intraday and not is_crypto
            places = 4 if is_crypto or stock_1d else 2
            if not series:
                items.append(
                    {
                        "ticker": t,
                        "asset_class": ac,
                        "first_value": None,
                        "last_value": None,
                        "change_pct": None,
                        "change_abs": None,
                        "pnl_usd": None,
                        "day_open": None,
                        "currency": "USD",
                        "session_status": session_status,
                        **_null_extended_fields(),
                    }
                )
                continue
            if stock_1d:
                ext = extended_change_meta(series, qty=qty, places=4)
                items.append(
                    {
                        "ticker": t,
                        "asset_class": ac,
                        "first_value": ext["first_value"],
                        "last_value": ext["last_value"],
                        "change_pct": ext["change_pct"],
                        "change_abs": ext["change_abs"],
                        "pnl_usd": ext["pnl_usd"],
                        "day_open": ext["day_open"],
                        "currency": "USD",
                        "session_status": session_status,
                        "prior_close": ext["prior_close"],
                        "change_since_close_abs": ext["change_since_close_abs"],
                        "change_since_close_pct": ext["change_since_close_pct"],
                        "change_rth_abs": ext["change_rth_abs"],
                        "change_rth_pct": ext["change_rth_pct"],
                        "pnl_rth_usd": ext["pnl_rth_usd"],
                        "rth_last": ext["rth_last"],
                    }
                )
                continue
            first, last = series[0].px, series[-1].px
            ch = _change_meta(first, last, places=places)
            pnl = qty * (last - first)
            items.append(
                {
                    "ticker": t,
                    "asset_class": ac,
                    "first_value": ch["first_value"],
                    "last_value": ch["last_value"],
                    "change_pct": ch["change_pct"],
                    "change_abs": ch["change_abs"],
                    "pnl_usd": _str_dec(pnl, 2),
                    "day_open": ch["first_value"],
                    "currency": "USD",
                    "session_status": session_status,
                    **_null_extended_fields(),
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
            "as_of": ts.isoformat(),
            "items": items,
        }
