"""
Deterministic AI-shaped helpers for the public writable sandbox demo.

Used when XAI_API_KEY is not set so "Try with your statements" still shows
categorize-suggest and cash CSV map UX without calling Grok.
"""

from __future__ import annotations

import re
from uuid import UUID

from backend.schema.default_categories import (
    CAT_COFFEE,
    CAT_GROCERIES,
    CAT_RESTAURANTS,
    CAT_SALARY,
    CAT_SOFTWARE,
    CAT_STREAMING,
    CAT_TAXI,
    CAT_UTILITIES,
)
from backend.schema.models import Category
from backend.services.ai_categorize import CategorySuggestion, MerchantCluster
from backend.services.ai_statement_map import ColumnMap

# label substring → preferred category id
_MERCHANT_HINTS: list[tuple[str, UUID]] = [
    ("lidl", CAT_GROCERIES),
    ("tesco", CAT_GROCERIES),
    ("albert", CAT_GROCERIES),
    ("billa", CAT_GROCERIES),
    ("kaufland", CAT_GROCERIES),
    ("rohlik", CAT_GROCERIES),
    ("starbucks", CAT_COFFEE),
    ("cafe", CAT_COFFEE),
    ("coffee", CAT_COFFEE),
    ("mcdonald", CAT_RESTAURANTS),
    ("restaurant", CAT_RESTAURANTS),
    ("uber", CAT_TAXI),
    ("bolt", CAT_TAXI),
    ("netflix", CAT_STREAMING),
    ("spotify", CAT_STREAMING),
    ("youtube", CAT_STREAMING),
    ("openai", CAT_SOFTWARE),
    ("github", CAT_SOFTWARE),
    ("microsoft", CAT_SOFTWARE),
    ("google", CAT_SOFTWARE),
    ("salary", CAT_SALARY),
    ("payroll", CAT_SALARY),
    ("mzda", CAT_SALARY),
    ("cez", CAT_UTILITIES),
    ("o2", CAT_UTILITIES),
    ("vodafone", CAT_UTILITIES),
    ("t-mobile", CAT_UTILITIES),
]


def suggest_merchants_heuristic(
    clusters: list[MerchantCluster],
    categories: list[Category],
    *,
    hint: str | None = None,
    hint_merchant_key: str | None = None,
) -> list[CategorySuggestion]:
    """
    Sandbox demo heuristics. Unknown merchants → needs_human (never Other).
    """
    by_id = {str(c.id): c for c in categories if not c.archived}
    hint_l = (hint or "").strip().lower()
    out: list[CategorySuggestion] = []
    for cl in clusters:
        label_l = cl.label.lower()
        blob = f"{label_l} {cl.description_sample.lower()}"
        if hint_l and (not hint_merchant_key or hint_merchant_key == cl.merchant_key):
            blob = f"{blob} {hint_l}"
        chosen: UUID | None = None
        reason = "sandbox demo match"
        for needle, cat_id in _MERCHANT_HINTS:
            if needle in blob and str(cat_id) in by_id:
                chosen = cat_id
                reason = f"sandbox demo · matched “{needle}”"
                break
        if chosen is None and cl.amount_sign == "in" and str(CAT_SALARY) in by_id:
            # Only map to salary when label looks like payroll
            if any(k in blob for k in ("salary", "payroll", "mzda", "wage")):
                chosen = CAT_SALARY
                reason = "sandbox demo · money-in payroll → Salary"
        if chosen is None or str(chosen) not in by_id:
            out.append(
                CategorySuggestion(
                    merchant_key=cl.merchant_key,
                    label=cl.label,
                    category_id="",
                    category_name="",
                    confidence=0.35,
                    reason="Needs you · no confident sandbox match",
                    transaction_ids=list(cl.transaction_ids),
                    sample_count=cl.sample_count,
                    needs_human=True,
                )
            )
            continue
        cat = by_id[str(chosen)]
        out.append(
            CategorySuggestion(
                merchant_key=cl.merchant_key,
                label=cl.label,
                category_id=str(chosen),
                category_name=cat.name or "",
                confidence=0.78 if "matched" in reason else 0.62,
                reason=reason,
                transaction_ids=list(cl.transaction_ids),
                sample_count=cl.sample_count,
                needs_human=False,
            )
        )
    out.sort(
        key=lambda s: (
            1 if s.needs_human else 0,
            -s.confidence,
            -s.sample_count,
            s.label.lower(),
        )
    )
    return out


def _score_header(name: str) -> str:
    n = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    if re.search(r"\b(date|datum|booking|value date|posted|trans.?date)\b", n):
        return "booking_date"
    if re.search(r"\b(amount|castka|částka|value|sum|credit|debit|price)\b", n):
        return "amount"
    if re.search(r"\b(currency|mena|měna|ccy|curr)\b", n):
        return "currency"
    if re.search(r"\b(merchant|payee|vendor|counterparty|name|obchodnik)\b", n):
        return "merchant"
    if re.search(r"\b(desc|description|popis|note|memo|details|message)\b", n):
        return "description"
    if re.search(r"\b(fee|poplatek)\b", n):
        return "fee"
    return "ignore"


def map_headers_heuristic(headers: list[str]) -> ColumnMap:
    columns = {h: _score_header(h) for h in headers}
    # Ensure single date / amount if multiples: keep first
    seen_date = False
    seen_amount = False
    for h in headers:
        role = columns[h]
        if role == "booking_date":
            if seen_date:
                columns[h] = "ignore"
            else:
                seen_date = True
        if role == "amount":
            if seen_amount:
                columns[h] = "ignore"
            else:
                seen_amount = True
    if not seen_date or not seen_amount:
        # Last resort: first col date-ish, second amount-ish
        if len(headers) >= 2:
            if not seen_date:
                columns[headers[0]] = "booking_date"
            if not seen_amount:
                columns[headers[1]] = "amount"
    roles = list(columns.values())
    if roles.count("booking_date") != 1 or roles.count("amount") != 1:
        raise ValueError(
            "Sandbox demo mapper could not find date/amount columns. "
            "Rename headers or use a standard bank CSV."
        )
    return ColumnMap(
        institution="Sandbox bank",
        default_currency="CZK",
        amount_sign="as_is",
        columns=columns,
        confidence=0.7,
        notes="Sandbox demo map (no Grok key) — confirm before import",
    )
