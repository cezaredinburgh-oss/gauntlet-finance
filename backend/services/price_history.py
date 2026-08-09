"""Historical price series for open positions (yfinance daily bars).

Ticker scope: daily close USD.
Asset-class scope: current open quantities × historical closes → mark MV series.

Does not persist OHLCV to Sheets. Process-level cache only.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Literal

from backend.common.timeutil import utc_now
from backend.schema.models import AssetClass, InvestmentLot, LotStatus
from backend.services.prices import _normalize_yahoo_symbol
from backend.sheets.repository import SheetsRepository

logger = logging.getLogger(__name__)

RangeKey = Literal["1m", "3m", "6m", "ytd", "1y", "5y", "max"]
ScopeKey = Literal["ticker", "asset_class"]

_RANGE_TO_PERIOD: dict[str, str] = {
    "1m": "1mo",
    "3m": "3mo",
    "6m": "6mo",
    "ytd": "ytd",
    "1y": "1y",
    "5y": "5y",
    "max": "max",
}

# Process cache: key -> (fetched_monotonic, closes_by_our_ticker)
_HISTORY_CACHE: dict[str, tuple[float, dict[str, list[tuple[date, Decimal]]]]] = {}

HistoryFetcher = Callable[
    [list[str], dict[str, str], str],
    dict[str, list[tuple[date, Decimal]]],
]


def range_to_yfinance_period(range_key: str) -> str:
    key = (range_key or "1y").strip().lower()
    if key not in _RANGE_TO_PERIOD:
        raise ValueError(
            f"Invalid range {range_key!r}; expected one of {sorted(_RANGE_TO_PERIOD)}"
        )
    return _RANGE_TO_PERIOD[key]


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


def _yfinance_history_batch(
    yahoo_symbols: list[str],
    yahoo_to_our: dict[str, str],
    period: str,
) -> dict[str, list[tuple[date, Decimal]]]:
    """Fetch daily closes; keys are our tickers."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is not installed") from exc

    if not yahoo_symbols:
        return {}

    out: dict[str, list[tuple[date, Decimal]]] = {}
    try:
        data = yf.download(
            tickers=" ".join(yahoo_symbols),
            period=period,
            interval="1d",
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
        series: list[tuple[date, Decimal]] = []
        try:
            if data is not None and not data.empty:
                if len(yahoo_symbols) == 1:
                    close = data["Close"].dropna()
                else:
                    if ysym not in data.columns.get_level_values(0):
                        continue
                    close = data[ysym]["Close"].dropna()
                for idx, val in close.items():
                    try:
                        d = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
                        series.append((d, Decimal(str(float(val)))))
                    except Exception:  # noqa: BLE001
                        continue
            if not series:
                t = yf.Ticker(ysym)
                hist = t.history(period=period, interval="1d", auto_adjust=True)
                if hist is not None and not hist.empty and "Close" in hist.columns:
                    for idx, val in hist["Close"].dropna().items():
                        d = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
                        series.append((d, Decimal(str(float(val)))))
        except Exception as exc:  # noqa: BLE001
            logger.warning("history failed for %s: %s", ysym, exc)
            continue
        if series:
            series.sort(key=lambda x: x[0])
            out[our] = series
    return out


def aggregate_mv_series(
    qty_by_ticker: dict[str, Decimal],
    closes_by_ticker: dict[str, list[tuple[date, Decimal]]],
) -> list[tuple[date, Decimal]]:
    """
    Forward-fill closes per ticker; sum qty * close on each union day.
    Skip days where no ticker has a known close yet.
    """
    if not qty_by_ticker:
        return []

    # Build date -> price maps
    price_maps: dict[str, dict[date, Decimal]] = {}
    all_dates: set[date] = set()
    for t, series in closes_by_ticker.items():
        if t not in qty_by_ticker:
            continue
        m: dict[date, Decimal] = {}
        for d, px in series:
            m[d] = px
            all_dates.add(d)
        if m:
            price_maps[t] = m

    if not all_dates or not price_maps:
        return []

    ordered = sorted(all_dates)
    last: dict[str, Decimal] = {}
    result: list[tuple[date, Decimal]] = []

    for d in ordered:
        for t, m in price_maps.items():
            if d in m:
                last[t] = m[d]
        if not last:
            continue
        total = Decimal("0")
        any_qty = False
        for t, qty in qty_by_ticker.items():
            if qty <= 0:
                continue
            px = last.get(t)
            if px is None:
                continue
            total += qty * px
            any_qty = True
        if any_qty:
            result.append((d, _q2(total)))
    return result


@dataclass
class HistoryResult:
    scope: str
    label: str
    range: str
    currency: str
    series_kind: str
    as_of: datetime
    points: list[dict[str, str]]
    meta: dict[str, Any] = field(default_factory=dict)


class PriceHistoryService:
    def __init__(
        self,
        repo: SheetsRepository,
        *,
        cache_ttl_seconds: int = 3600,
        enabled: bool = True,
        fetcher: HistoryFetcher | None = None,
    ) -> None:
        self.repo = repo
        self.cache_ttl = cache_ttl_seconds
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

    def _qty_and_cost_by_ticker(
        self,
        lots: list[InvestmentLot],
        *,
        asset_class: AssetClass | None = None,
        ticker: str | None = None,
    ) -> tuple[dict[str, Decimal], Decimal, dict[str, str | None]]:
        qty: dict[str, Decimal] = {}
        cost = Decimal("0")
        ac_map: dict[str, str | None] = {}
        for lot in lots:
            t = lot.ticker.upper()
            if ticker is not None and t != ticker.upper():
                continue
            if asset_class is not None:
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
    ) -> dict[str, list[tuple[date, Decimal]]]:
        yahoo_map: dict[str, str] = {}
        for t in tickers:
            ysym = _normalize_yahoo_symbol(t, asset_classes.get(t))
            yahoo_map[ysym] = t.upper()
        yahoo_symbols = list(yahoo_map.keys())
        cache_key = f"{period}|{'|'.join(sorted(yahoo_symbols))}"
        now_m = time.monotonic()
        if cache_key in _HISTORY_CACHE:
            fetched, payload = _HISTORY_CACHE[cache_key]
            if now_m - fetched <= self.cache_ttl:
                return payload

        payload = self._fetcher(yahoo_symbols, yahoo_map, period)
        _HISTORY_CACHE[cache_key] = (time.monotonic(), payload)
        return payload

    def history(
        self,
        *,
        scope: ScopeKey,
        range_key: RangeKey | str = "1y",
        ticker: str | None = None,
        asset_class: str | None = None,
    ) -> HistoryResult:
        if not self.enabled:
            raise RuntimeError("yfinance disabled")

        period = range_to_yfinance_period(str(range_key))
        range_norm = str(range_key).strip().lower()
        lots = self._open_lots()
        ts = utc_now()

        if scope == "ticker":
            if not ticker or not ticker.strip():
                raise ValueError("ticker is required when scope=ticker")
            t = ticker.strip().upper()
            qty_map, cost, ac_map = self._qty_and_cost_by_ticker(lots, ticker=t)
            if not qty_map:
                raise LookupError(f"No open position for {t}")
            closes = self._fetch_closes([t], ac_map, period)
            series = closes.get(t, [])
            missing = [] if series else [t]
            qty = qty_map[t]
            avg_cost = (cost / qty) if qty > 0 else None
            points = [{"date": d.isoformat(), "value": _str_dec(px, 4)} for d, px in series]
            first = series[0][1] if series else None
            last = series[-1][1] if series else None
            change_pct = None
            if first is not None and last is not None and first != 0:
                change_pct = float(((last - first) / first) * 100)
            return HistoryResult(
                scope="ticker",
                label=t,
                range=range_norm,
                currency="USD",
                series_kind="price",
                as_of=ts,
                points=points,
                meta={
                    "tickers": [t],
                    "missing_tickers": missing,
                    "cost_basis_usd": _str_dec(cost),
                    "avg_cost_usd": _str_dec(avg_cost, 4) if avg_cost is not None else None,
                    "quantity": str(_q4(qty)),
                    "first_value": _str_dec(first, 4) if first is not None else None,
                    "last_value": _str_dec(last, 4) if last is not None else None,
                    "change_pct": round(change_pct, 2) if change_pct is not None else None,
                    "quantity_basis": "current_open_lots",
                    "note": "Daily close (USD). Avg cost from open lots.",
                },
            )

        if scope == "asset_class":
            if not asset_class or not asset_class.strip():
                raise ValueError("asset_class is required when scope=asset_class")
            ac_raw = asset_class.strip()
            try:
                ac = AssetClass(ac_raw)
            except ValueError as exc:
                # Accept lowercase
                try:
                    ac = AssetClass(ac_raw.capitalize())
                except ValueError:
                    raise ValueError(
                        f"Invalid asset_class {asset_class!r}; expected Stock or Crypto"
                    ) from exc

            qty_map, cost, ac_map = self._qty_and_cost_by_ticker(lots, asset_class=ac)
            if not qty_map:
                raise LookupError(f"No open {ac.value} positions")
            tickers = sorted(qty_map.keys())
            closes = self._fetch_closes(tickers, ac_map, period)
            missing = [t for t in tickers if t not in closes or not closes[t]]
            mv_series = aggregate_mv_series(qty_map, closes)
            points = [{"date": d.isoformat(), "value": _str_dec(v)} for d, v in mv_series]
            first = mv_series[0][1] if mv_series else None
            last = mv_series[-1][1] if mv_series else None
            change_pct = None
            if first is not None and last is not None and first != 0:
                change_pct = float(((last - first) / first) * 100)
            return HistoryResult(
                scope="asset_class",
                label=ac.value,
                range=range_norm,
                currency="USD",
                series_kind="market_value",
                as_of=ts,
                points=points,
                meta={
                    "tickers": tickers,
                    "missing_tickers": missing,
                    "cost_basis_usd": _str_dec(cost),
                    "avg_cost_usd": None,
                    "quantity": None,
                    "first_value": _str_dec(first) if first is not None else None,
                    "last_value": _str_dec(last) if last is not None else None,
                    "change_pct": round(change_pct, 2) if change_pct is not None else None,
                    "quantity_basis": "current_open_lots",
                    "note": "Mark of current holdings at historical closes.",
                },
            )

        raise ValueError(f"Invalid scope {scope!r}")
