"""
Deterministic vendor → leaf-category pass used by Ask Grok+.

Cheap rules first (pots, FX, ATM, loans, fees, card-unwrap, known shops).
Leftovers go to Grok. Never writes the ledger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.services.ai_categorize import MerchantCluster

_PREFIX = re.compile(
    r"^(?:card payment(?: google pay)?|internet transaction google pay|"
    r"single payment)\s*[—\-–]\s*",
    re.I,
)
_INTERNAL = re.compile(
    r"\b("
    r"to pocket|from pocket|purchase vault|from vault|to vault|"
    r"exchanged to|exchanged from|exchange to|"
    r"top-?up|top up|pocket withdrawal|balance migration|"
    r"to czk|to eur|to usd|to pln"
    r")\b",
    re.I,
)
_CASH = re.compile(r"\b(cash withdrawal|atm)\b", re.I)
_LOAN = re.compile(
    r"\b(loan interest|loan repayment|credit instalment|loan instalment|"
    r"consumer loan)\b",
    re.I,
)
_FEE = re.compile(
    r"\b(account maintenance|alert fee|metal plan fee|custody fee|"
    r"statement distribution|express issuing|accounted fee)\b",
    re.I,
)
_SPACE = re.compile(r"\s+")

# lowercase label → leaf category name (resolved against the app catalog).
KNOWN_MERCHANTS: dict[str, str] = {
    "albert": "Groceries",
    "lidl": "Groceries",
    "rohlik.cz": "Groceries",
    "potraviny": "Groceries",
    "biedronka": "Groceries",
    "billa": "Groceries",
    "tesco": "Groceries",
    "carrefour": "Groceries",
    "auchan": "Groceries",
    "żabka": "Groceries",
    "zabka": "Groceries",
    "lime": "Taxi / rideshare",
    "bolt": "Taxi / rideshare",
    "uber": "Taxi / rideshare",
    "uber *trip": "Taxi / rideshare",
    "berider": "Taxi / rideshare",
    "anytime carsharing": "Taxi / rideshare",
    "foodora": "Restaurants",
    "damejidlo.cz": "Restaurants",
    "mcdonald's": "Restaurants",
    "mcdonalds": "Restaurants",
    "wolt": "Restaurants",
    "deliveroo": "Restaurants",
    "uber eats": "Restaurants",
    "bolt food": "Restaurants",
    "vodafone": "Internet / phone",
    "spotify": "Spotify",
    "netflix": "Streaming",
    "youtube": "Streaming",
    "audible": "Streaming",
    "amazon prime": "Streaming",
    "openai": "Software",
    "midjourney": "Software",
    "xai": "Software",
    "steam": "Software",
    "dropbox": "Software",
    "alza": "Electronics",
    "apple": "Electronics",
    "amazon": "Electronics",
    "ikea": "General shopping",
    "obi": "General shopping",
    "hornbach": "General shopping",
    "mol": "Fuel (car)",
    "omv": "Fuel (car)",
    "orlen": "Fuel (car)",
    "orlen benzina": "Fuel (car)",
    "shell": "Fuel (car)",
    "bp": "Fuel (car)",
    "lítačka": "Public transit",
    "litacka": "Public transit",
    "české dráhy": "Public transit",
    "ceske drahy": "Public transit",
    "revolut": "Internal transfer",
    "revolut bank uab": "Internal transfer",
    "etoro": "Broker funding",
    "pražská plynárenská": "Utilities",
    "prazska plynarenska": "Utilities",
    "pražská energetika": "Utilities",
    "prazska energetika": "Utilities",
    "allianz": "Insurance",
}


@dataclass(frozen=True)
class LocalGuess:
    cluster: MerchantCluster
    category_id: str
    category_name: str
    reason: str


@dataclass(frozen=True)
class PreclassifyResult:
    resolved: list[LocalGuess]
    leftovers: list[MerchantCluster]


def _norm(s: str) -> str:
    return _SPACE.sub(" ", (s or "").strip())


def unwrap_vendor_label(label: str) -> str:
    """Strip bank-narrative wrappers so 'Card payment — Lidl; Praha' → 'Lidl'."""
    text = _norm(label)
    text = _PREFIX.sub("", text)
    if ";" in text:
        text = text.split(";", 1)[0]
    text = re.sub(r"^\d[\d\s.,]*\s*(usd|eur|pln|huf|czk|gbp)\s*", "", text, flags=re.I)
    return _norm(text).strip(" —-")


def _catalog_by_name(catalog: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in catalog:
        name = (row.get("name") or "").strip().lower()
        cid = (row.get("id") or "").strip()
        if name and cid:
            out[name] = row
    return out


def _guess_for(
    cluster: MerchantCluster,
    names: dict[str, dict[str, str]],
) -> LocalGuess | None:
    raw = _norm(cluster.label)
    core = unwrap_vendor_label(raw)
    blob = f"{raw} {cluster.description_sample or ''} {core}"

    def hit(cat_name: str, reason: str) -> LocalGuess | None:
        row = names.get(cat_name.lower())
        if not row:
            return None
        return LocalGuess(
            cluster=cluster,
            category_id=row["id"],
            category_name=row["name"],
            reason=reason,
        )

    if _INTERNAL.search(blob):
        return hit("Internal transfer", "Own pot / FX / top-up")
    if _CASH.search(blob):
        return hit("Cash withdrawal", "ATM / cash withdrawal")
    if _LOAN.search(blob):
        return hit("Loans", "Loan instalment")
    if _FEE.search(blob):
        return hit("Bank fees", "Bank / plan fee")

    for candidate in (core, raw):
        key = candidate.lower()
        cat_name = KNOWN_MERCHANTS.get(key)
        if cat_name:
            return hit(cat_name, f"Known merchant → {cat_name}")
    return None


def preclassify_clusters(
    clusters: list[MerchantCluster],
    catalog: list[dict[str, str]],
) -> PreclassifyResult:
    """Split residual vendor clusters into local guesses vs Grok leftovers."""
    names = _catalog_by_name(catalog)
    resolved: list[LocalGuess] = []
    leftovers: list[MerchantCluster] = []
    for cluster in clusters:
        guess = _guess_for(cluster, names)
        if guess is None:
            leftovers.append(cluster)
        else:
            resolved.append(guess)
    return PreclassifyResult(resolved=resolved, leftovers=leftovers)
