"""Spending / data-quality / portfolio alerts for the Alerts tab."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from backend.schema.models import (
    Category,
    InvestmentEvent,
    InvestmentLot,
    LotStatus,
    Price,
    Transaction,
)
from backend.services.dashboard import _expense_usd_in_window
from backend.services.dca_opportunities import build_dca_alerts
from backend.services.fx_amounts import (
    build_fx_service,
    enrich_and_backfill_transactions,
    tx_signed_usd,
)
from backend.services.periods import pct_change
from backend.sheets.repository import SheetsRepository

_TRANSFER_LEAK = re.compile(
    r"\b(transfer|top.?up|topup|sent to|from revolut|to revolut|"
    r"own account|me to me|me2me|vlastn[ií]|p[rř]evod)\b",
    re.I,
)

# Domains where a transfer-like narrative has been deliberately bucketed.
_TRANSFER_LEAK_RESOLVED_DOMAINS = frozenset({"Transfers", "Investments"})


def transfer_leak_resolved(tx: Transaction, cat: Category | None) -> bool:
    """
    True when a transfer-like expense no longer needs the unflagged-transfer alert.

    Revolut labels many peer P2P payments as \"Transfer to NAME\". Those are real
    spend when the user assigns a living category (e.g. Going out / Fitness).

    Resolved when:
    - already flagged internal, or
    - categorized into Transfers / Investments / any is_transfer category, or
    - categorized into any non-Other life domain (user/rules assigned meaning), or
    - category_override is set (explicit human review, including Other).
    Still fires for uncategorized rows and default Other dump without override.
    """
    if tx.is_internal_transfer:
        return True
    if cat is None:
        return False
    if cat.is_transfer:
        return True
    domain = cat.life_domain.value if cat.life_domain else ""
    if domain in _TRANSFER_LEAK_RESOLVED_DOMAINS:
        return True
    # Peer \"Transfer to …\" put in Food/Entertainment/etc. is intentional spend.
    if domain and domain != "Other":
        return True
    if tx.category_override:
        return True
    return False


def looks_like_transfer_narrative(tx: Transaction) -> bool:
    """True if merchant/description/etc. match the transfer-leak keyword pattern."""
    blob = " ".join(
        filter(
            None,
            [tx.merchant, tx.description, tx.original_description, tx.counterparty_name],
        )
    )
    return bool(_TRANSFER_LEAK.search(blob or ""))


def _cat_url(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: str | None = None,
    q: str | None = None,
    life_domain: str | None = None,
    expenses_only: bool = True,
    hide_transfers: bool = True,
    unconverted: bool = False,
    filter_flag: str | None = None,
) -> str:
    """Build /expenses/categorize drill-down like Dashboard chart clicks."""
    from urllib.parse import urlencode

    params: dict[str, str] = {}
    if date_from:
        params["date_from"] = date_from.isoformat()
    if date_to:
        params["date_to"] = date_to.isoformat()
    if expenses_only:
        params["expenses_only"] = "1"
    if hide_transfers:
        params["hide_transfers"] = "1"
    if category_id:
        params["category_id"] = category_id
    if q:
        params["q"] = q[:80]
    if life_domain:
        params["life_domain"] = life_domain
    if unconverted:
        params["unconverted"] = "1"
    if filter_flag:
        params["filter"] = filter_flag
    qs = urlencode(params)
    return f"/expenses/categorize?{qs}" if qs else "/expenses/categorize"


def build_alerts(
    repo: SheetsRepository,
    *,
    persist_fx: bool = False,
    exemption_days: int = 1095,
) -> dict[str, Any]:
    # Never flush Transactions on alerts GET (see dashboard_summary note).
    raw = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    fx = build_fx_service(repo)
    txs = enrich_and_backfill_transactions(raw, repo, fx, persist=persist_fx)
    cats = {
        c.id: c
        for c in repo.list_rows("Categories")
        if isinstance(c, Category) and not c.archived
    }

    today = date.today()
    d30_from = today - timedelta(days=29)
    d180_from = today - timedelta(days=179)
    spend_30 = _expense_usd_in_window(txs, fx, d30_from, today)
    spend_180 = _expense_usd_in_window(txs, fx, d180_from, today)
    avg_monthly = spend_180 / Decimal("6") if spend_180 else Decimal("0")
    pace = pct_change(float(spend_30), float(avg_monthly)) if avg_monthly > 0 else None

    alerts: list[dict[str, Any]] = []

    # --- Existing: pace ---
    if pace is not None and pace > 50:
        alerts.append(
            {
                "id": "pace_far_above_avg",
                "level": "danger",
                "title": "Spending far above average",
                "body": (
                    f"Last 30 days spend is {pace:.0f}% above your 6‑month monthly average "
                    f"(${spend_30:,.0f} vs ${avg_monthly:,.0f}/mo)."
                ),
                "href": _cat_url(date_from=d30_from, date_to=today),
            }
        )
    elif pace is not None and pace > 15:
        alerts.append(
            {
                "id": "pace_above_avg",
                "level": "warn",
                "title": "Spending above average",
                "body": (
                    f"Last 30 days spend is {pace:.0f}% above your 6‑month monthly average "
                    f"(${spend_30:,.0f} vs ${avg_monthly:,.0f}/mo)."
                ),
                "href": _cat_url(date_from=d30_from, date_to=today),
            }
        )

    # --- Existing: largest outflow ---
    largest: Transaction | None = None
    largest_usd = Decimal("0")
    for t in txs:
        if t.archived or t.is_internal_transfer or t.amount >= 0:
            continue
        if t.booking_date < d30_from or t.booking_date > today:
            continue
        signed = tx_signed_usd(t, fx)
        if signed is None:
            continue
        mag = abs(signed)
        if mag > largest_usd:
            largest_usd = mag
            largest = t
    if largest and spend_30 > 0 and largest_usd > spend_30 * Decimal("0.25"):
        label = largest.merchant or largest.description or "Transaction"
        alerts.append(
            {
                "id": "large_outflow",
                "level": "info",
                "title": "Large recent outflow",
                "body": (
                    f"{label}: ${largest_usd:,.0f} on {largest.booking_date.isoformat()} "
                    f"({float(largest_usd / spend_30) * 100:.0f}% of 30‑day spend)."
                ),
                "href": _cat_url(
                    date_from=d30_from,
                    date_to=today,
                    q=(largest.merchant or largest.description or "")[:60] or None,
                ),
            }
        )

    # --- Existing: fixed costs ---
    month_start = date(today.year, today.month, 1)
    fixed = Decimal("0")
    for t in txs:
        if t.archived or t.is_internal_transfer or t.amount >= 0:
            continue
        if t.booking_date < month_start or t.booking_date > today:
            continue
        cat = cats.get(t.category_id) if t.category_id else None
        if not cat or cat.necessity.value != "Fixed":
            continue
        signed = tx_signed_usd(t, fx)
        if signed is not None and signed < 0:
            fixed += abs(signed)
    if fixed > 0:
        alerts.append(
            {
                "id": "fixed_this_month",
                "level": "info",
                "title": "Fixed costs this month",
                "body": f"About ${fixed:,.0f} of Fixed-category spend booked so far this month.",
                "href": _cat_url(
                    date_from=month_start,
                    date_to=today,
                    filter_flag="fixed",
                ),
            }
        )

    # --- Existing: unconverted FX ---
    unconverted = 0
    for t in txs:
        if t.archived or t.is_internal_transfer:
            continue
        if t.booking_date < d180_from:
            continue
        if tx_signed_usd(t, fx) is None:
            unconverted += 1
    if unconverted > 0:
        alerts.append(
            {
                "id": "unconverted_fx",
                "level": "warn",
                "title": "Missing FX conversion",
                "body": (
                    f"{unconverted} transaction(s) in the last 6 months lack a USD conversion "
                    f"(no CNB rate path). They are excluded from USD totals."
                ),
                "href": _cat_url(
                    date_from=d180_from,
                    date_to=today,
                    unconverted=True,
                    expenses_only=False,
                ),
            }
        )

    # --- 5.1 Uncategorized % (30d) ---
    exp_30 = Decimal("0")
    uncat_30 = Decimal("0")
    for t in txs:
        if t.archived or t.is_internal_transfer or t.amount >= 0:
            continue
        if t.booking_date < d30_from or t.booking_date > today:
            continue
        signed = tx_signed_usd(t, fx)
        if signed is None or signed >= 0:
            continue
        mag = abs(signed)
        exp_30 += mag
        cat = cats.get(t.category_id) if t.category_id else None
        if cat is None or cat.life_domain.value == "Other":
            uncat_30 += mag
    if exp_30 > 0:
        uncat_pct = float(uncat_30 / exp_30 * 100)
        if uncat_pct >= 40:
            alerts.append(
                {
                    "id": "uncategorized_high",
                    "level": "danger",
                    "title": "High uncategorized spend",
                    "body": (
                        f"{uncat_pct:.0f}% of last-30d expense (${uncat_30:,.0f} of ${exp_30:,.0f}) "
                        f"is uncategorized or Other. Open Categorize to fix."
                    ),
                    "href": _cat_url(
                        date_from=d30_from,
                        date_to=today,
                        category_id="uncategorized",
                    ),
                }
            )
        elif uncat_pct >= 20:
            alerts.append(
                {
                    "id": "uncategorized_pct",
                    "level": "warn",
                    "title": "Uncategorized spend",
                    "body": (
                        f"{uncat_pct:.0f}% of last-30d expense (${uncat_30:,.0f}) lacks a real category."
                    ),
                    "href": _cat_url(
                        date_from=d30_from,
                        date_to=today,
                        category_id="uncategorized",
                    ),
                }
            )

    # --- 5.2 Tax unlocks soon ---
    lots = [
        r
        for r in repo.list_rows("InvestmentLots")
        if isinstance(r, InvestmentLot)
        and not r.archived
        and r.status == LotStatus.OPEN
        and r.quantity_remaining > 0
    ]
    soon_90: list[InvestmentLot] = []
    soon_180: list[InvestmentLot] = []
    for lot in lots:
        free_on = lot.acquisition_date + timedelta(days=exemption_days)
        days_left = (free_on - today).days
        if days_left <= 0:
            continue
        if days_left <= 90:
            soon_90.append(lot)
        elif days_left <= 180:
            soon_180.append(lot)
    if soon_90:
        basis = sum((lot.cost_basis_usd or Decimal("0") for lot in soon_90), Decimal("0"))
        level = "warn" if basis >= Decimal("5000") else "info"
        alerts.append(
            {
                "id": "tax_unlocks_90",
                "level": level,
                "title": "Lots unlock tax-free soon",
                "body": (
                    f"{len(soon_90)} open lot(s) become tax-free within 90 days "
                    f"(~${basis:,.0f} cost basis). Prefer these for draws after unlock."
                ),
                "href": "/investments?focus=tax_runway",
            }
        )
    elif soon_180:
        basis = sum((lot.cost_basis_usd or Decimal("0") for lot in soon_180), Decimal("0"))
        alerts.append(
            {
                "id": "tax_unlocks_180",
                "level": "info",
                "title": "Lots aging into tax-free",
                "body": (
                    f"{len(soon_180)} open lot(s) unlock within 6 months "
                    f"(~${basis:,.0f} cost basis)."
                ),
                "href": "/investments?focus=tax_runway",
            }
        )

    # --- 5.3 Missing prices ---
    prices = {
        p.ticker.upper()
        for p in repo.list_rows("Prices")
        if isinstance(p, Price) and not p.archived
    }
    open_tickers = sorted({lot.ticker.upper() for lot in lots})
    missing = [t for t in open_tickers if t not in prices]
    if missing:
        alerts.append(
            {
                "id": "missing_prices",
                "level": "warn",
                "title": "Missing market prices",
                "body": (
                    f"{len(missing)} open ticker(s) have no quote: "
                    f"{', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}. "
                    f"Open Investments — marks refresh automatically on that page."
                ),
                "href": "/investments?focus=prices",
            }
        )

    # --- 5.4 Unusual domain spend ---
    domain_30: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    domain_180: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for t in txs:
        if t.archived or t.is_internal_transfer or t.amount >= 0:
            continue
        if t.booking_date < d180_from or t.booking_date > today:
            continue
        signed = tx_signed_usd(t, fx)
        if signed is None or signed >= 0:
            continue
        cat = cats.get(t.category_id) if t.category_id else None
        domain = cat.life_domain.value if cat else "Other"
        mag = abs(signed)
        domain_180[domain] += mag
        if t.booking_date >= d30_from:
            domain_30[domain] += mag
    for domain, amt30 in domain_30.items():
        if domain in ("Transfers", "Investments", "Income"):
            continue
        avg_m = domain_180[domain] / Decimal("6")
        if amt30 > Decimal("100") and avg_m > 0 and amt30 > avg_m * Decimal("2"):
            alerts.append(
                {
                    "id": f"domain_spike_{domain}",
                    "level": "warn",
                    "title": f"Unusual {domain} spend",
                    "body": (
                        f"{domain}: ${amt30:,.0f} in last 30 days vs "
                        f"~${avg_m:,.0f}/mo average over 6 months."
                    ),
                    "href": _cat_url(
                        date_from=d30_from,
                        date_to=today,
                        life_domain=domain,
                    ),
                }
            )

    # --- 5.5 Internal-transfer leak ---
    # Fire only for transfer-like expenses that are still unreviewed: not flagged
    # internal and not assigned to Transfers/Investments (or any is_transfer cat).
    leak_count = 0
    leak_usd = Decimal("0")
    sample = ""
    for t in txs:
        if t.archived or t.amount >= 0:
            continue
        if t.booking_date < d180_from or t.booking_date > today:
            continue
        cat = cats.get(t.category_id) if t.category_id else None
        if transfer_leak_resolved(t, cat):
            continue
        if not looks_like_transfer_narrative(t):
            continue
        signed = tx_signed_usd(t, fx)
        if signed is None:
            continue
        mag = abs(signed)
        if mag < Decimal("50"):
            continue
        leak_count += 1
        leak_usd += mag
        if not sample:
            sample = t.merchant or t.description or "transfer-like row"
    if leak_count > 0:
        alerts.append(
            {
                "id": "transfer_leak",
                "level": "warn",
                "title": "Possible unflagged internal transfers",
                "body": (
                    f"{leak_count} uncategorized (or Other) expense row(s) look like "
                    f"transfers (~${leak_usd:,.0f}) and are not marked internal "
                    f"(e.g. “{sample}”). Categorize them or flag Internal transfer "
                    f"to clear this alert. Peer payments already in spend categories "
                    f"are ignored."
                ),
                "href": _cat_url(
                    date_from=d180_from,
                    date_to=today,
                    filter_flag="transfer_leak",
                ),
            }
        )

    # --- DCA opportunities on existing open positions ---
    # Signal A: mark clearly below avg cost. Signal B: 3M pullback and/or
    # drawdown below 52-week average (Yahoo history, fail-open).
    try:
        price_by_ticker = {
            p.ticker.upper(): p
            for p in repo.list_rows("Prices")
            if isinstance(p, Price) and not p.archived
        }
        events = [
            r
            for r in repo.list_rows("InvestmentEvents")
            if isinstance(r, InvestmentEvent)
        ]
        dca_items = build_dca_alerts(
            lots,
            events,
            price_by_ticker,
            as_of=today,
            fetch_history=True,
        )
        alerts.extend(dca_items)
    except Exception:  # noqa: BLE001 — never break spend/tax alerts
        pass

    warn_count = sum(1 for a in alerts if a["level"] in ("warn", "danger"))
    danger_count = sum(1 for a in alerts if a["level"] == "danger")
    return {
        "items": alerts,
        "warn_count": warn_count,
        "danger_count": danger_count,
        "total": len(alerts),
    }
