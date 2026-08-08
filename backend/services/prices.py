"""Fast multi-ticker price refresh via yfinance."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from backend.common.timeutil import utc_now
from backend.schema.models import InvestmentLot, LotStatus, Price
from backend.sheets.repository import SheetsRepository

logger = logging.getLogger(__name__)

# Process-wide cache: ticker -> (price, currency, fetched_at_monotonic)
_PRICE_CACHE: dict[str, tuple[Decimal, str, float]] = {}


@dataclass
class PriceQuote:
    ticker: str
    price: Decimal
    currency: str
    as_of: datetime
    source: str = "yfinance"


@dataclass
class PortfolioValuation:
    as_of: datetime
    quotes: list[PriceQuote]
    positions: list[dict[str, Any]] = field(default_factory=list)
    total_market_value_usd: Decimal | None = None
    errors: list[str] = field(default_factory=list)


def _normalize_yahoo_symbol(ticker: str, asset_class: str | None = None) -> str:
    t = ticker.strip().upper()
    # Crypto on Yahoo often uses -USD
    if asset_class and asset_class.lower() == "crypto":
        if not t.endswith("-USD") and "-" not in t:
            return f"{t}-USD"
    return t


class PriceService:
    def __init__(
        self,
        repo: SheetsRepository,
        *,
        cache_ttl_seconds: int = 60,
        enabled: bool = True,
    ) -> None:
        self.repo = repo
        self.cache_ttl = cache_ttl_seconds
        self.enabled = enabled

    def open_tickers(self) -> list[tuple[str, str | None]]:
        """Return (ticker, asset_class) for open lots."""
        seen: dict[str, str | None] = {}
        for row in self.repo.list_rows("InvestmentLots"):
            if not isinstance(row, InvestmentLot):
                continue
            if row.archived or row.status != LotStatus.OPEN or row.quantity_remaining <= 0:
                continue
            ac = row.asset_class.value if row.asset_class else None
            seen.setdefault(row.ticker.upper(), ac)
        return list(seen.items())

    def fetch_quotes(
        self,
        tickers: list[str] | None = None,
        *,
        asset_classes: dict[str, str | None] | None = None,
        force: bool = False,
    ) -> list[PriceQuote]:
        if not self.enabled:
            return []

        now_m = time.monotonic()
        ts = utc_now()
        asset_classes = asset_classes or {}

        if tickers is None:
            pairs = self.open_tickers()
            want = [t for t, _ in pairs]
            for t, ac in pairs:
                asset_classes.setdefault(t, ac)
        else:
            want = [t.upper() for t in tickers]

        if not want:
            return []

        to_fetch: list[str] = []
        yahoo_map: dict[str, str] = {}  # yahoo symbol -> our ticker
        cached: list[PriceQuote] = []

        for t in want:
            if not force and t in _PRICE_CACHE:
                price, ccy, fetched = _PRICE_CACHE[t]
                if now_m - fetched <= self.cache_ttl:
                    cached.append(
                        PriceQuote(ticker=t, price=price, currency=ccy, as_of=ts)
                    )
                    continue
            ysym = _normalize_yahoo_symbol(t, asset_classes.get(t))
            yahoo_map[ysym] = t
            to_fetch.append(ysym)

        if to_fetch:
            fetched_quotes = self._yfinance_batch(to_fetch, yahoo_map, ts)
            for q in fetched_quotes:
                _PRICE_CACHE[q.ticker] = (q.price, q.currency, time.monotonic())
            cached.extend(fetched_quotes)

        return cached

    def _yfinance_batch(
        self,
        yahoo_symbols: list[str],
        yahoo_map: dict[str, str],
        ts: datetime,
    ) -> list[PriceQuote]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("yfinance is not installed") from exc

        quotes: list[PriceQuote] = []
        # Single download call for speed
        try:
            data = yf.download(
                tickers=" ".join(yahoo_symbols),
                period="5d",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("yfinance download failed: %s", exc)
            data = None

        for ysym in yahoo_symbols:
            our = yahoo_map[ysym]
            price = None
            try:
                if data is not None and not data.empty:
                    if len(yahoo_symbols) == 1:
                        close = data["Close"].dropna()
                        if len(close):
                            price = Decimal(str(float(close.iloc[-1])))
                    else:
                        # Multi-index columns
                        if ysym in data.columns.get_level_values(0):
                            close = data[ysym]["Close"].dropna()
                            if len(close):
                                price = Decimal(str(float(close.iloc[-1])))
                if price is None:
                    # Fallback: Ticker.fast_info / info
                    t = yf.Ticker(ysym)
                    fi = getattr(t, "fast_info", None)
                    last = None
                    if fi is not None:
                        last = getattr(fi, "last_price", None) or (
                            fi.get("lastPrice") if hasattr(fi, "get") else None
                        )
                    if last is None:
                        hist = t.history(period="5d")
                        if hist is not None and not hist.empty:
                            last = float(hist["Close"].iloc[-1])
                    if last is not None:
                        price = Decimal(str(float(last)))
            except Exception as exc:  # noqa: BLE001
                logger.warning("price failed for %s: %s", ysym, exc)
                continue
            if price is None:
                continue
            quotes.append(
                PriceQuote(
                    ticker=our,
                    price=price,
                    currency="USD",
                    as_of=ts,
                    source="yfinance",
                )
            )
        return quotes

    def refresh_and_store(self, *, force: bool = False) -> PortfolioValuation:
        pairs = self.open_tickers()
        asset_classes = {t: ac for t, ac in pairs}
        quotes = self.fetch_quotes(
            [t for t, _ in pairs],
            asset_classes=asset_classes,
            force=force,
        )
        errors: list[str] = []
        quote_map = {q.ticker: q for q in quotes}
        missing = [t for t, _ in pairs if t not in quote_map]
        if missing:
            errors.append(f"No price for: {', '.join(sorted(missing)[:20])}")

        # Persist Prices tab (upsert by ticker: replace previous row for ticker)
        existing = [
            r for r in self.repo.list_rows("Prices") if isinstance(r, Price)
        ]
        by_ticker = {p.ticker.upper(): p for p in existing if not p.archived}
        ts = utc_now()
        to_write: list[Price] = []
        for q in quotes:
            prev = by_ticker.get(q.ticker.upper())
            to_write.append(
                Price(
                    id=prev.id if prev else uuid4(),
                    ticker=q.ticker.upper(),
                    price=q.price,
                    currency=q.currency,
                    as_of=q.as_of,
                    source=q.source,
                    created_at=prev.created_at if prev else ts,
                    updated_at=ts,
                )
            )
        if to_write:
            self.repo.upsert_rows("Prices", to_write)

        # Build positions
        positions: list[dict[str, Any]] = []
        total = Decimal("0")
        for row in self.repo.list_rows("InvestmentLots"):
            if not isinstance(row, InvestmentLot):
                continue
            if row.archived or row.status != LotStatus.OPEN or row.quantity_remaining <= 0:
                continue
            q = quote_map.get(row.ticker.upper())
            mv = None
            upnl = None
            if q is not None:
                mv = (row.quantity_remaining * q.price).quantize(Decimal("0.01"))
                upnl = (mv - row.cost_basis_usd).quantize(Decimal("0.01"))
                total += mv
            positions.append(
                {
                    "lot_id": str(row.id),
                    "ticker": row.ticker,
                    "quantity": str(row.quantity_remaining),
                    "cost_basis_usd": str(row.cost_basis_usd),
                    "price": str(q.price) if q else None,
                    "price_currency": q.currency if q else None,
                    "market_value": str(mv) if mv is not None else None,
                    "unrealized_pnl_usd": str(upnl) if upnl is not None else None,
                }
            )

        return PortfolioValuation(
            as_of=ts,
            quotes=quotes,
            positions=positions,
            total_market_value_usd=total if quotes else None,
            errors=errors,
        )
