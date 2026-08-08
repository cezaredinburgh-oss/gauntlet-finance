"""
CNB-oriented FX conversion service.

Rates are quote units per 1 base (e.g. CZK per 1 USD). Accept injected
historical rates; optionally parse CNB daily text or fetch via URL opener
(injectable for tests — no hard network dependency in unit tests).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Iterable
from urllib.error import URLError
from urllib.request import urlopen

from backend.schema.models import FXRate, FXSource

_CNB_LINE = re.compile(
    r"^(?P<country>.+?)\|(?P<currency>[A-Za-z ]+)\|(?P<amount>\d+)\|(?P<code>[A-Z]{3})\|(?P<rate>[\d.,]+)\s*$"
)


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q8(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


@dataclass
class FXService:
    """
    In-memory FX table with CNB-preferring lookup and graceful fallback.

    ``convert`` never raises for missing rates — returns None (caller decides).

    Rates are indexed by (base, quote) for O(log n) date lookback instead of
    scanning the full table per transaction (critical for ~10k+ dashboard rows).
    """

    rates: list[FXRate] = field(default_factory=list)
    preferred_source: str = FXSource.CNB.value
    # Inject for tests: (url: str) -> bytes
    urlopen_bytes: Callable[[str], bytes] | None = None
    # (base, quote) -> sorted list of (rate_date, rate, is_preferred)
    _index: dict[tuple[str, str], list[tuple[date, Decimal, bool]]] = field(
        default_factory=dict, repr=False
    )
    # (from_ccy, to_ccy, on) -> rate factor (1 unit from -> to)
    _factor_cache: dict[tuple[str, str, date], Decimal | None] = field(
        default_factory=dict, repr=False
    )
    _index_dirty: bool = field(default=True, repr=False)

    def __post_init__(self) -> None:
        self._rebuild_index()

    def load_rates(self, rates: Iterable[FXRate], *, replace: bool = False) -> None:
        if replace:
            self.rates = list(rates)
        else:
            self.rates.extend(rates)
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        idx: dict[tuple[str, str], list[tuple[date, Decimal, bool]]] = {}
        pref = self.preferred_source
        for r in self.rates:
            if r.archived:
                continue
            key = (r.base_currency.upper(), r.quote_currency.upper())
            bucket = idx.setdefault(key, [])
            bucket.append((r.rate_date, r.rate, r.source.value == pref))
        for key, bucket in idx.items():
            # preferred first on same date, then by date ascending
            bucket.sort(key=lambda x: (x[0], 0 if x[2] else 1))
            # Keep best per date (first after sort = preferred when available)
            best: dict[date, Decimal] = {}
            for d, rate, _is_pref in bucket:
                if d not in best:
                    best[d] = rate
            idx[key] = sorted((d, rate, True) for d, rate in best.items())
        self._index = idx
        self._factor_cache.clear()
        self._index_dirty = False

    def rate_for(
        self,
        *,
        on: date,
        base: str,
        quote: str,
        preferred_source: str | None = None,
        max_lookback_days: int = 14,
    ) -> Decimal | None:
        """
        Units of ``quote`` per 1 ``base`` on or before ``on``.

        Preference order:
        1. Exact date + preferred source
        2. Exact date + any source
        3. Nearest prior date (within lookback) preferred source
        4. Nearest prior date any source
        """
        del preferred_source  # preference folded into index build
        if self._index_dirty:
            self._rebuild_index()

        base_u = base.upper()
        quote_u = quote.upper()
        if base_u == quote_u:
            return Decimal("1")

        hit = self._lookup_pair(base_u, quote_u, on, max_lookback_days)
        if hit is not None:
            return hit

        # Inverse pair if we only store USD/CZK but need CZK/USD
        inv = self._lookup_pair(quote_u, base_u, on, max_lookback_days)
        if inv is not None and inv != 0:
            return _q8(Decimal("1") / inv)

        return None

    def _lookup_pair(
        self,
        base: str,
        quote: str,
        on: date,
        max_lookback_days: int,
    ) -> Decimal | None:
        series = self._index.get((base, quote))
        if not series:
            return None
        # Binary search: last entry with date <= on
        lo, hi = 0, len(series) - 1
        best_i = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if series[mid][0] <= on:
                best_i = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best_i < 0:
            return None
        d, rate, _ = series[best_i]
        if (on - d).days > max_lookback_days:
            return None
        return rate

    def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        on: date,
        *,
        quantize: bool = True,
    ) -> Decimal | None:
        """
        Convert ``amount`` from ``from_currency`` to ``to_currency`` on ``on``.

        Uses quote-per-base rates. Falls back via inverse and lookback.
        Returns None if no rate path is available.
        """
        frm = from_currency.upper()
        to = to_currency.upper()
        if frm == to:
            return _q2(amount) if quantize else amount

        factor = self._factor(frm, to, on)
        if factor is None:
            return None
        out = amount * factor
        return _q2(out) if quantize else out

    def _factor(self, frm: str, to: str, on: date) -> Decimal | None:
        """Cached multiplier: 1 unit of frm → to."""
        key = (frm, to, on)
        if key in self._factor_cache:
            return self._factor_cache[key]

        if frm == to:
            self._factor_cache[key] = Decimal("1")
            return Decimal("1")

        # Prefer path through CZK when both non-CZK (cross via CZK)
        if frm != "CZK" and to != "CZK":
            a = self._factor(frm, "CZK", on)
            b = self._factor("CZK", to, on)
            result = (a * b) if (a is not None and b is not None) else None
            self._factor_cache[key] = result
            return result

        if to == "CZK":
            rate = self.rate_for(on=on, base=frm, quote="CZK")
            self._factor_cache[key] = rate
            return rate

        if frm == "CZK":
            rate = self.rate_for(on=on, base=to, quote="CZK")
            if rate is None or rate == 0:
                self._factor_cache[key] = None
                return None
            result = Decimal("1") / rate
            self._factor_cache[key] = result
            return result

        self._factor_cache[key] = None
        return None

    # ------------------------------------------------------------------
    # CNB daily text helpers (optional network)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_cnb_daily_text(text: str, rate_date: date) -> list[tuple[str, Decimal]]:
        """
        Parse CNB daily exchange rate file body.

        Returns list of (currency_code, CZK per 1 unit), already divided by
        CNB ``amount`` (e.g. 100 JPY). ``rate_date`` is accepted for API
        symmetry (date is chosen by the caller / fetch URL).
        """
        del rate_date  # date comes from fetch URL / caller context
        out: list[tuple[str, Decimal]] = []
        for line in text.splitlines():
            line = line.strip()
            m = _CNB_LINE.match(line)
            if not m:
                continue
            code = m.group("code").upper()
            amount = Decimal(m.group("amount"))
            rate_raw = m.group("rate").replace(",", ".")
            rate = Decimal(rate_raw)
            per_unit = rate / amount
            out.append((code, per_unit))
        return out

    def fetch_cnb_rates_for_date(
        self,
        on: date,
        *,
        build_fx_rate: Callable[..., FXRate] | None = None,
    ) -> list[FXRate]:
        """
        Fetch CNB daily rates for ``on`` and append to this service.

        Network is optional — inject ``urlopen_bytes`` in tests.
        """
        # CNB expects dd.mm.yyyy
        q = on.strftime("%d.%m.%Y")
        url = (
            "https://www.cnb.cz/en/financial_markets/foreign_exchange_market/"
            f"exchange_rate_fixing/daily.txt?date={q}"
        )
        opener = self.urlopen_bytes
        if opener is None:
            def opener(u: str) -> bytes:  # type: ignore[misc]
                with urlopen(u, timeout=20) as resp:  # noqa: S310 — trusted CNB URL
                    return resp.read()

        try:
            raw = opener(url)
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"CNB fetch failed for {on}: {exc}") from exc

        text = raw.decode("utf-8", errors="replace")
        pairs = self.parse_cnb_daily_text(text, on)
        if not pairs:
            raise RuntimeError(f"CNB returned no currency rows for {on}")

        from datetime import datetime, timezone
        from uuid import uuid4

        ts = datetime.now(timezone.utc)
        created: list[FXRate] = []
        for code, rate in pairs:
            row = FXRate(
                id=uuid4(),
                rate_date=on,
                base_currency=code,
                quote_currency="CZK",
                rate=rate,
                source=FXSource.CNB,
                created_at=ts,
                updated_at=ts,
            )
            created.append(row)
        self.load_rates(created)
        return created
