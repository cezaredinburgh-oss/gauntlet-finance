"""Book-level portfolio health score (Desk portfolio_health parity, no pandas)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

SPECULATIVE = frozenset({"DOGE", "ENJ", "ACHR", "NNE", "QS"})

GRADE_SUMMARY = {
    "A": "Structurally healthy for a retail book — watch concentration and keep draws tax-efficient.",
    "B": "Generally usable, with a few structural risks to manage while living off sales.",
    "C": "Workable but fragile for spend-down — address concentration and/or tax runway.",
    "D": "Elevated risk for funding living costs from this book — prioritize tax-free lots and ballast.",
    "N/A": "No open holdings.",
}


@dataclass
class HoldingRow:
    ticker: str
    value: Decimal  # MV if priced else cost
    cost_basis_usd: Decimal
    asset_class: str  # stock|crypto|etf|other
    is_crypto: bool = False


@dataclass
class LotRow:
    ticker: str
    cost_basis_usd: Decimal
    tax_free: bool
    days_until_tax_free: int | None


@dataclass
class RealizedRow:
    tax_free: bool
    gain_usd: Decimal


def _d(v: Decimal | float | int | str | None) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _grade(score: int) -> str:
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def compute_portfolio_health(
    holdings: Sequence[HoldingRow],
    lots: Sequence[LotRow],
    realized: Sequence[RealizedRow],
    *,
    tax_free_open_basis: Decimal,
    open_cost_basis: Decimal,
) -> dict[str, Any]:
    """Return score, grade, summary, issues, concentration metrics."""
    if not holdings:
        return {
            "score": 0,
            "grade": "N/A",
            "summary": GRADE_SUMMARY["N/A"],
            "issues": [],
            "concentration": {
                "top_ticker": None,
                "top_weight_pct": 0.0,
                "top3_weight_pct": 0.0,
                "hhi": 0.0,
                "crypto_weight_pct": 0.0,
                "tax_free_basis_pct": 0.0,
                "largest_position_line": "No open holdings",
            },
        }

    total = sum((h.value for h in holdings), Decimal("0"))
    if total <= 0:
        total = sum((h.cost_basis_usd for h in holdings), Decimal("0")) or Decimal("1")

    weights: list[tuple[str, float, HoldingRow]] = []
    for h in holdings:
        w = float(h.value / total) if total else 0.0
        weights.append((h.ticker, w, h))
    weights.sort(key=lambda x: x[1], reverse=True)

    hhi = sum(w * w for _, w, _ in weights)
    top_ticker, top_w_frac, _ = weights[0]
    top_w = top_w_frac * 100
    top3_w = sum(w for _, w, _ in weights[:3]) * 100
    crypto_val = sum((h.value for h in holdings if h.is_crypto), Decimal("0"))
    crypto_w = float(crypto_val / total * 100) if total else 0.0

    open_basis = open_cost_basis if open_cost_basis > 0 else Decimal("1")
    free_pct = float(tax_free_open_basis / open_basis * 100)

    issues: list[dict[str, str]] = []
    score = 100

    # Single-name
    if top_w > 35:
        score -= 18
        issues.append(
            {
                "severity": "high",
                "title": f"Heavy single-name concentration: {top_ticker}",
                "detail": (
                    f"{top_ticker} is ~{top_w:.0f}% of the book. Living-off risk rises if this name stalls; "
                    f"prefer funding draws from tax-free lots across multiple names."
                ),
            }
        )
    elif top_w > 25:
        score -= 10
        issues.append(
            {
                "severity": "medium",
                "title": f"Elevated weight in {top_ticker}",
                "detail": f"~{top_w:.0f}% in one ticker. Fine as a conviction bet, but plan sales across lots.",
            }
        )
    else:
        issues.append(
            {
                "severity": "good",
                "title": "Single-name concentration OK",
                "detail": f"Largest position ~{top_w:.0f}%.",
            }
        )

    # Top 3
    if top3_w > 70:
        score -= 12
        issues.append(
            {
                "severity": "high",
                "title": "Top 3 names dominate",
                "detail": f"Top 3 = {top3_w:.0f}% of portfolio. Diversification is thin for a spend-down phase.",
            }
        )
    elif top3_w > 55:
        score -= 6
        issues.append(
            {
                "severity": "medium",
                "title": "Top-heavy book",
                "detail": f"Top 3 = {top3_w:.0f}%.",
            }
        )

    # Crypto
    if crypto_w > 50:
        score -= 15
        issues.append(
            {
                "severity": "high",
                "title": "Crypto-heavy book",
                "detail": (
                    f"~{crypto_w:.0f}% crypto. High path-dependency for living expenses; "
                    f"keep a multi-month cash buffer from tax-free stock sales."
                ),
            }
        )
    elif crypto_w > 30:
        score -= 8
        issues.append(
            {
                "severity": "medium",
                "title": "Material crypto allocation",
                "detail": f"~{crypto_w:.0f}% crypto — volatile funding source for living costs.",
            }
        )
    else:
        issues.append(
            {
                "severity": "good",
                "title": "Crypto allocation contained",
                "detail": f"~{crypto_w:.0f}% of book.",
            }
        )

    # Tax runway
    if free_pct < 10:
        score -= 14
        issues.append(
            {
                "severity": "high",
                "title": "Thin tax-free sell runway",
                "detail": (
                    f"Only ~{free_pct:.0f}% of open cost basis is past 3 years. "
                    f"Avoid selling young lots for living costs if you can wait."
                ),
            }
        )
    elif free_pct < 25:
        score -= 7
        issues.append(
            {
                "severity": "medium",
                "title": "Limited tax-free runway",
                "detail": f"~{free_pct:.0f}% of basis is tax-free eligible. Prioritize those lots for draws.",
            }
        )
    else:
        issues.append(
            {
                "severity": "good",
                "title": "Usable tax-free runway",
                "detail": f"~{free_pct:.0f}% of open cost basis is ≥3y (cost-basis view).",
            }
        )

    # Early sales
    if realized:
        early = [r for r in realized if not r.tax_free]
        early_pct = len(early) / len(realized) * 100
        early_gain = sum((r.gain_usd for r in early), Decimal("0"))
        if early_pct > 40 and early_gain > 0:
            score -= 10
            issues.append(
                {
                    "severity": "medium",
                    "title": "Many sales inside 3-year window",
                    "detail": (
                        f"{early_pct:.0f}% of matched sell lots were <3y (FIFO). "
                        f"Review habit vs your CZ exemption preference."
                    ),
                }
            )
        elif early_pct <= 20:
            issues.append(
                {
                    "severity": "good",
                    "title": "Sales mostly respect 3-year rule",
                    "detail": f"Only {early_pct:.0f}% of sell lots were taxable-window.",
                }
            )

    # Speculative sleeve
    spec_val = sum(
        (h.value for h in holdings if h.ticker.upper() in SPECULATIVE),
        Decimal("0"),
    )
    spec_w = float(spec_val / total * 100) if total else 0.0
    if spec_w > 25:
        score -= 8
        issues.append(
            {
                "severity": "medium",
                "title": "High speculative sleeve",
                "detail": (
                    f"~{spec_w:.0f}% in higher-risk names (meme crypto / pre-revenue style bets). "
                    f"Fine as satellite — not as living-cost core."
                ),
            }
        )

    # Aging soon
    soon = [
        lot
        for lot in lots
        if not lot.tax_free
        and lot.days_until_tax_free is not None
        and 0 < lot.days_until_tax_free <= 180
    ]
    if soon:
        soon_basis = sum((lot.cost_basis_usd for lot in soon), Decimal("0"))
        issues.append(
            {
                "severity": "good",
                "title": "Lots aging into tax-free soon",
                "detail": (
                    f"{len(soon)} lot(s) become tax-free within ~6 months "
                    f"(basis ${soon_basis:,.0f}). Avoid selling those early if cash allows."
                ),
            }
        )

    score = max(0, min(100, score))
    grade = _grade(score)
    line = f"Largest position: {top_ticker} ({top_w:.0f}%)"

    return {
        "score": score,
        "grade": grade,
        "summary": GRADE_SUMMARY[grade],
        "issues": issues,
        "concentration": {
            "top_ticker": top_ticker,
            "top_weight_pct": round(top_w, 2),
            "top3_weight_pct": round(top3_w, 2),
            "hhi": round(hhi, 4),
            "crypto_weight_pct": round(crypto_w, 2),
            "tax_free_basis_pct": round(free_pct, 2),
            "largest_position_line": line,
        },
    }


def holdings_from_positions(
    positions: Iterable[Mapping[str, Any]],
    *,
    asset_class_by_ticker: Mapping[str, str] | None = None,
) -> list[HoldingRow]:
    """Build HoldingRow list from snapshot-style position dicts."""
    asset_class_by_ticker = asset_class_by_ticker or {}
    rows: list[HoldingRow] = []
    for p in positions:
        ticker = str(p.get("ticker") or "").upper()
        if not ticker:
            continue
        cost = _d(p.get("cost_basis_usd"))
        mv = p.get("market_value")
        value = _d(mv) if mv is not None else cost
        cls = (asset_class_by_ticker.get(ticker) or p.get("asset_class") or "other").lower()
        is_crypto = cls == "crypto" or "crypto" in cls
        rows.append(
            HoldingRow(
                ticker=ticker,
                value=value,
                cost_basis_usd=cost,
                asset_class=cls,
                is_crypto=is_crypto,
            )
        )
    return rows


def price_status_from_snapshot(
    *,
    quote_count: int,
    open_ticker_count: int,
    missing_quotes: Sequence[str],
    prices_as_of: date | None,
    as_of: date | None = None,
    stale_hours: int = 36,
) -> dict[str, Any]:
    """Structured price quality for banners."""
    as_of = as_of or date.today()
    missing = list(missing_quotes or [])
    if quote_count <= 0 or open_ticker_count <= 0:
        mode = "empty"
        note = "No market quotes — showing cost basis where needed. Use Update prices."
    elif missing:
        mode = "partial"
        note = (
            f"Mixed marks · {len(missing)} open ticker(s) missing quotes"
            + (f" ({', '.join(missing[:6])}{'…' if len(missing) > 6 else ''})" if missing else "")
        )
    else:
        mode = "live_ok"
        when = prices_as_of.isoformat() if prices_as_of else "—"
        note = f"Live marks · as of {when}"

    # Optional stale: only if we have a prices_as_of and it's old (date-level approx)
    if mode == "live_ok" and prices_as_of is not None:
        age_days = (as_of - prices_as_of).days
        if age_days >= 2:  # ~36h+ on calendar day basis
            mode = "stale"
            note = f"Quotes may be stale · as of {prices_as_of.isoformat()} · refresh prices"

    return {
        "mode": mode,
        "quote_count": quote_count,
        "open_ticker_count": open_ticker_count,
        "missing_quotes": missing,
        "prices_as_of": prices_as_of.isoformat() if prices_as_of else None,
        "note": note,
        "mode_note": "Broker statements · CNB historical FX · fees & staking included",
    }
