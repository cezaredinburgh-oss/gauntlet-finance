"""Universal core pack: tag-only hints for import and Grok+.

Never writes category_id. Structural own-money hits may set is_internal_transfer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from backend.schema.models import Category, Transaction

_SPACE = re.compile(r"\s+")
_PREFIX = re.compile(
    r"^(?:card payment(?: google pay)?|internet transaction google pay|"
    r"single payment)\s*[—\-–]\s*",
    re.I,
)
_INTERNAL = re.compile(
    r"\b("
    r"to pocket|from pocket|purchase vault|from vault|to vault|"
    r"exchanged to|exchanged from|exchange to|"
    r"pocket withdrawal|balance migration|"
    r"between own accounts|to main account|"
    r"revolut digital assets europe"
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

# Exact unwrapped label → leaf category name. Keep this list tiny.
EXACT_SHOPS: dict[str, str] = {
    "spotify": "Spotify",
    "netflix": "Streaming",
    "mcdonald's": "Restaurants",
    "mcdonalds": "Restaurants",
}


@dataclass(frozen=True)
class CoreHit:
    category_id: UUID
    category_name: str
    reason: str
    set_internal: bool


def _norm(s: str) -> str:
    return _SPACE.sub(" ", (s or "").strip())


def unwrap_vendor_label(label: str) -> str:
    text = _norm(label)
    text = _PREFIX.sub("", text)
    if ";" in text:
        text = text.split(";", 1)[0]
    text = re.sub(r"^\d[\d\s.,]*\s*(usd|eur|pln|huf|czk|gbp)\s*", "", text, flags=re.I)
    return _norm(text).strip(" —-")


def _catalog_by_name(categories: list[Category]) -> dict[str, Category]:
    out: dict[str, Category] = {}
    for c in categories:
        if getattr(c, "archived", False):
            continue
        name = (c.name or "").strip().lower()
        if name:
            out[name] = c
    return out


def match_core_pack(
    label: str,
    description: str,
    categories: list[Category],
) -> CoreHit | None:
    names = _catalog_by_name(categories)
    raw = _norm(label)
    core = unwrap_vendor_label(raw)
    blob = f"{raw} {description or ''} {core}"

    def hit(cat_name: str, reason: str, internal: bool) -> CoreHit | None:
        row = names.get(cat_name.lower())
        if not row:
            return None
        return CoreHit(
            category_id=row.id,
            category_name=row.name,
            reason=reason,
            set_internal=internal,
        )

    if _INTERNAL.search(blob):
        if "digital assets europe" in blob.lower():
            crypto = hit("Crypto funding", "Digital Assets Europe cash leg", True)
            if crypto:
                return crypto
        return hit("Internal transfer", "Own pot / FX / vault", True)
    if _CASH.search(blob):
        return hit("Cash withdrawal", "ATM / cash withdrawal", False)
    if _LOAN.search(blob):
        return hit("Loans", "Loan instalment", False)
    if _FEE.search(blob):
        return hit("Bank fees", "Bank / plan fee", False)

    for candidate in (core, raw):
        cat_name = EXACT_SHOPS.get(candidate.lower())
        if cat_name:
            return hit(cat_name, f"Core exact merchant → {cat_name}", False)
    return None


def tag_transaction(tx: Transaction, categories: list[Category]) -> Transaction:
    """Apply core-pack tag. Never sets category_id."""
    blob_label = tx.merchant or tx.description or tx.original_description or ""
    desc = " ".join(
        p
        for p in (tx.description, tx.original_description, tx.merchant)
        if p
    )
    hit = match_core_pack(blob_label, desc, categories)
    if hit is None:
        return tx
    updates: dict = {
        "suggest_category_id": hit.category_id,
        "suggest_source": "core",
        "suggest_reason": hit.reason,
    }
    if hit.set_internal:
        updates["is_internal_transfer"] = True
    return tx.model_copy(update=updates)


def tag_transactions(
    txs: list[Transaction],
    categories: list[Category],
) -> tuple[list[Transaction], int, int]:
    """Return tagged rows, tag count, newly flagged internal count."""
    out: list[Transaction] = []
    tagged = 0
    flagged = 0
    for tx in txs:
        nxt = tag_transaction(tx, categories)
        if nxt.suggest_category_id is not None:
            tagged += 1
        if nxt.is_internal_transfer and not tx.is_internal_transfer:
            flagged += 1
        out.append(nxt)
    return out, tagged, flagged
