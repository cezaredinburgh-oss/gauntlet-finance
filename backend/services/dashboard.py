"""Dashboard aggregate numbers for the React UI — USD-primary analytics."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from backend.schema.models import Category, Transaction
from backend.services.fx_amounts import (
    build_fx_service,
    enrich_and_backfill_transactions,
    tx_signed_czk,
    tx_signed_usd,
)
from backend.services.periods import PeriodKey, pct_change, prior_range
from backend.services.portfolio_snapshot import portfolio_snapshot
from backend.sheets.repository import SheetsRepository


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def _str_dec(v: Decimal) -> str:
    return str(_q2(v))


def _in_range(d: date, date_from: date | None, date_to: date | None) -> bool:
    if date_from and d < date_from:
        return False
    if date_to and d > date_to:
        return False
    return True


def _cashflow_window(
    txs: list[Transaction],
    fx,
    cat_map: dict,
    date_from: date | None,
    date_to: date | None,
    *,
    currency_filter: str | None = None,
    top_n: int = 5,
) -> dict[str, Any]:
    income_usd = Decimal("0")
    expense_usd = Decimal("0")
    income_czk = Decimal("0")
    expense_czk = Decimal("0")
    by_ccy: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"income": Decimal("0"), "expense": Decimal("0")}
    )
    top_income: dict[str, dict[str, Any]] = {}
    top_exp_merch: dict[str, dict[str, Any]] = {}
    top_exp_domain: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_domain: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_necessity: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    # cat_id str -> {name, life_domain, necessity, amount_usd}
    by_category: dict[str, dict[str, Any]] = {}
    unconverted = 0
    tx_count = 0
    transfer_count = 0
    uncategorized_exp = Decimal("0")
    total_exp_for_cat = Decimal("0")

    for t in txs:
        if t.archived:
            continue
        if not _in_range(t.booking_date, date_from, date_to):
            continue
        if currency_filter and t.currency.upper() != currency_filter.upper():
            continue
        tx_count += 1
        if t.is_internal_transfer:
            transfer_count += 1
            continue

        signed = tx_signed_usd(t, fx)
        if signed is None:
            unconverted += 1
            continue
        signed_czk = tx_signed_czk(t, fx)
        ccy = t.currency.upper()
        label = (t.merchant or t.counterparty_name or t.description or "Unknown").strip()
        if not label:
            label = "Unknown"

        if signed > 0:
            income_usd += signed
            by_ccy[ccy]["income"] += t.amount
            if signed_czk is not None and signed_czk > 0:
                income_czk += signed_czk
            bucket = top_income.setdefault(label, {"label": label, "amount_usd": Decimal("0"), "count": 0})
            bucket["amount_usd"] += signed
            bucket["count"] += 1
        elif signed < 0:
            exp = abs(signed)
            expense_usd += exp
            by_ccy[ccy]["expense"] += abs(t.amount)
            if signed_czk is not None and signed_czk < 0:
                expense_czk += abs(signed_czk)
            bucket = top_exp_merch.setdefault(
                label, {"label": label, "amount_usd": Decimal("0"), "count": 0}
            )
            bucket["amount_usd"] += exp
            bucket["count"] += 1

            cat = cat_map.get(t.category_id) if t.category_id else None
            domain = cat.life_domain.value if cat else "Other"
            nec = cat.necessity.value if cat else "Discretionary"
            by_domain[domain] += exp
            by_necessity[nec] += exp
            top_exp_domain[domain] += exp
            total_exp_for_cat += exp
            if not cat or domain == "Other":
                uncategorized_exp += exp

            cat_key = str(cat.id) if cat else "uncategorized"
            if cat_key not in by_category:
                by_category[cat_key] = {
                    "id": cat_key,
                    "name": cat.name if cat else "Uncategorized",
                    "life_domain": domain,
                    "necessity": nec,
                    "amount_usd": Decimal("0"),
                }
            by_category[cat_key]["amount_usd"] += exp

    def top_list(d: dict[str, dict[str, Any]], n: int) -> list[dict[str, Any]]:
        items = sorted(d.values(), key=lambda x: x["amount_usd"], reverse=True)[:n]
        return [
            {
                "label": i["label"],
                "amount_usd": _str_dec(i["amount_usd"]),
                "count": i["count"],
            }
            for i in items
        ]

    uncategorized_pct = (
        float((uncategorized_exp / total_exp_for_cat) * 100) if total_exp_for_cat > 0 else 0.0
    )

    by_category_list: list[dict[str, Any]] = []
    for row in sorted(by_category.values(), key=lambda x: x["amount_usd"], reverse=True):
        amt = row["amount_usd"]
        pct = float((amt / total_exp_for_cat) * 100) if total_exp_for_cat > 0 else 0.0
        by_category_list.append(
            {
                "id": row["id"],
                "name": row["name"],
                "amount_usd": _str_dec(amt),
                "life_domain": row["life_domain"],
                "necessity": row["necessity"],
                "pct_of_spend": round(pct, 1),
            }
        )

    return {
        "income_usd": income_usd,
        "expense_usd": expense_usd,
        "net_usd": income_usd - expense_usd,
        "income_czk": income_czk,
        "expense_czk": expense_czk,
        "net_czk": income_czk - expense_czk,
        "by_currency": [
            {
                "currency": c,
                "income": _str_dec(v["income"]),
                "expense": _str_dec(v["expense"]),
                "net": _str_dec(v["income"] - v["expense"]),
            }
            for c, v in sorted(by_ccy.items())
        ],
        "top_income": top_list(top_income, top_n),
        "top_expense_merchants": top_list(top_exp_merch, top_n),
        "top_expense_domains": [
            {"label": k, "amount_usd": _str_dec(v), "count": 0}
            for k, v in sorted(top_exp_domain.items(), key=lambda x: x[1], reverse=True)[:top_n]
        ],
        "unconverted_count": unconverted,
        "transaction_count": tx_count,
        "internal_transfer_count": transfer_count,
        "by_domain": [
            {"name": k, "amount_usd": _str_dec(v)}
            for k, v in sorted(by_domain.items(), key=lambda x: x[1], reverse=True)
        ],
        "by_necessity": [
            {"name": k, "amount_usd": _str_dec(v)}
            for k, v in sorted(by_necessity.items(), key=lambda x: x[1], reverse=True)
        ],
        "by_category": by_category_list,
        "uncategorized_expense_usd": uncategorized_exp,
        "uncategorized_pct": uncategorized_pct,
    }


def _expense_split_in_window(
    txs: list[Transaction],
    fx,
    cat_map: dict,
    date_from: date,
    date_to: date,
) -> tuple[Decimal, Decimal]:
    """Return (total_expense_usd, investment_expense_usd) for the window."""
    total = Decimal("0")
    investments = Decimal("0")
    for t in txs:
        if t.archived or t.is_internal_transfer:
            continue
        if not _in_range(t.booking_date, date_from, date_to):
            continue
        if t.amount >= 0:
            continue
        signed = tx_signed_usd(t, fx)
        if signed is None or signed >= 0:
            continue
        exp = abs(signed)
        total += exp
        cat = cat_map.get(t.category_id) if t.category_id else None
        if cat is not None and cat.life_domain.value == "Investments":
            investments += exp
    return total, investments


def _expense_usd_in_window(
    txs: list[Transaction],
    fx,
    date_from: date,
    date_to: date,
    cat_map: dict | None = None,
) -> Decimal:
    """Total expense USD in window. Optional cat_map kept for call-site compatibility."""
    total, _ = _expense_split_in_window(txs, fx, cat_map or {}, date_from, date_to)
    return total


def dashboard_summary(
    repo: SheetsRepository,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    currency: str | None = None,
    period_key: str | None = None,
    exemption_days: int = 1095,
    persist_fx: bool = False,
) -> dict[str, Any]:
    # Default persist_fx=False: never rewrite the Transactions tab on a GET.
    # A full tab flush of ~14k rows is multi-minute and freezes the UI.
    raw_txs = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    fx = build_fx_service(repo)
    txs = enrich_and_backfill_transactions(raw_txs, repo, fx, persist=persist_fx)

    cats = [r for r in repo.list_rows("Categories") if isinstance(r, Category) and not r.archived]
    cat_map = {c.id: c for c in cats}

    today = date.today()
    if date_to is None:
        date_to = today

    key: PeriodKey = "custom"
    if period_key in (
        "this_month",
        "last_month",
        "last_30d",
        "last_6m",
        "this_year",
        "last_year",
        "all_time",
        "custom",
        "calendar_month",
    ):
        key = period_key  # type: ignore[assignment]

    main = _cashflow_window(txs, fx, cat_map, date_from, date_to, currency_filter=currency)

    # Prior period
    prior = prior_range(key, date_from, date_to, today=today)
    comparison: dict[str, Any] | None = None
    if prior is not None:
        p_from, p_to = prior
        pwin = _cashflow_window(txs, fx, cat_map, p_from, p_to, currency_filter=currency)
        comparison = {
            "prior_from": p_from.isoformat() if p_from else None,
            "prior_to": p_to.isoformat() if p_to else None,
            "income_usd": _str_dec(pwin["income_usd"]),
            "expense_usd": _str_dec(pwin["expense_usd"]),
            "net_usd": _str_dec(pwin["net_usd"]),
            "income_change_pct": pct_change(float(main["income_usd"]), float(pwin["income_usd"])),
            "expense_change_pct": pct_change(float(main["expense_usd"]), float(pwin["expense_usd"])),
            "net_change_pct": pct_change(float(main["net_usd"]), float(pwin["net_usd"])),
        }

    # Pace strip (fixed windows ending today)
    d30_from = today - timedelta(days=29)
    d180_from = today - timedelta(days=179)
    spend_30, inv_30 = _expense_split_in_window(txs, fx, cat_map, d30_from, today)
    spend_180, inv_180 = _expense_split_in_window(txs, fx, cat_map, d180_from, today)
    avg_monthly = spend_180 / Decimal("6")
    avg_monthly_inv = inv_180 / Decimal("6")
    living_30 = max(spend_30 - inv_30, Decimal("0"))
    living_avg = max(avg_monthly - avg_monthly_inv, Decimal("0"))
    pace_pct = pct_change(float(spend_30), float(avg_monthly)) if avg_monthly > 0 else None
    pace_pct_living = (
        pct_change(float(living_30), float(living_avg)) if living_avg > 0 else None
    )
    inv_share_30 = float((inv_30 / spend_30) * 100) if spend_30 > 0 else None
    inv_share_6m = float((avg_monthly_inv / avg_monthly) * 100) if avg_monthly > 0 else None

    snap = portfolio_snapshot(repo, as_of=today, exemption_days=exemption_days)

    # Backward-compatible cashflow keys + new USD keys
    return {
        "filters": {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "currency": currency,
            "period_key": key,
        },
        "cashflow": {
            "transaction_count": main["transaction_count"],
            "internal_transfer_count": main["internal_transfer_count"],
            # legacy (now USD)
            "income": _str_dec(main["income_usd"]),
            "expense": _str_dec(main["expense_usd"]),
            "net": _str_dec(main["net_usd"]),
            "income_usd": _str_dec(main["income_usd"]),
            "expense_usd": _str_dec(main["expense_usd"]),
            "net_usd": _str_dec(main["net_usd"]),
            "income_czk": _str_dec(main["income_czk"]),
            "expense_czk": _str_dec(main["expense_czk"]),
            "net_czk": _str_dec(main["net_czk"]),
            "by_currency": main["by_currency"],
            "top_income": main["top_income"],
            "top_expense_merchants": main["top_expense_merchants"],
            "top_expense_domains": main["top_expense_domains"],
            "unconverted_count": main["unconverted_count"],
            "expense_by_currency": {
                row["currency"]: row["expense"] for row in main["by_currency"]
            },
        },
        "comparison": comparison,
        "pace": {
            "spend_30d_usd": _str_dec(spend_30),
            "spend_30d_investments_usd": _str_dec(inv_30),
            "spend_30d_living_usd": _str_dec(living_30),
            "avg_monthly_6m_usd": _str_dec(avg_monthly),
            "avg_monthly_6m_investments_usd": _str_dec(avg_monthly_inv),
            "avg_monthly_6m_living_usd": _str_dec(living_avg),
            "pace_pct": pace_pct,
            "pace_pct_living": pace_pct_living,
            "investments_share_30d_pct": inv_share_30,
            "investments_share_6m_avg_pct": inv_share_6m,
        },
        "spending": {
            "by_domain": main["by_domain"],
            "by_necessity": main["by_necessity"],
            "by_category": main["by_category"],
            "uncategorized_expense_usd": _str_dec(main["uncategorized_expense_usd"]),
            "uncategorized_pct": main["uncategorized_pct"],
        },
        "portfolio": {
            "ticker_count": snap["ticker_count"],
            "positions_with_tax_free_qty": sum(
                1
                for p in snap["positions"]
                if Decimal(p["quantity_tax_free"]) > 0
            ),
            "total_cost_basis_usd": snap["total_cost_basis_usd"],
            "total_cost_basis_czk": snap["total_cost_basis_czk"],
            "total_market_value": snap["total_market_value_usd"],
            "unrealized_usd": snap["unrealized_usd"],
            "unrealized_pct": snap["unrealized_pct"],
            "tax_free_now_usd": snap["tax_free_now_usd"],
            "prices_as_of": snap["prices_as_of"],
            "top_tickers_by_cost": snap["top_tickers_by_cost"],
            "positions": [
                {
                    "ticker": p["ticker"],
                    "quantity": p["quantity"],
                    "quantity_tax_free": p["quantity_tax_free"],
                    "quantity_pending": p["quantity_pending"],
                    "cost_basis_usd": p["cost_basis_usd"],
                    "price": p["price"],
                    "market_value": p["market_value"],
                }
                for p in snap["positions"]
            ],
        },
        "portfolio_compact": {
            "total_cost_basis_usd": snap["total_cost_basis_usd"],
            "total_cost_basis_czk": snap["total_cost_basis_czk"],
            "total_market_value_usd": snap["total_market_value_usd"],
            "unrealized_usd": snap["unrealized_usd"],
            "unrealized_pct": snap["unrealized_pct"],
            "tax_free_now_usd": snap["tax_free_now_usd"],
            "ticker_count": snap["ticker_count"],
            "prices_as_of": snap["prices_as_of"],
            "top_tickers_by_cost": snap["top_tickers_by_cost"],
            "living_draw_12m": snap.get("living_draw_12m"),
            "health": (
                {
                    "grade": snap["health"]["grade"],
                    "score": snap["health"]["score"],
                    "summary": snap["health"]["summary"],
                }
                if snap.get("health")
                else None
            ),
            "price_status": snap.get("price_status"),
        },
    }
