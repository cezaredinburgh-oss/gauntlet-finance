"""
Internal-transfer matcher.

Precision over recall: only auto-link high-confidence pairs (same currency,
opposing signs, different accounts, tight amount + date windows, optional
keyword boost). Uncertain candidates are left unmatched for manual review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from backend.schema.models import Transaction

# Strong signals that a leg is an own-account move
_HINT_RE = re.compile(
    r"(sent from revolut|internal|own account|me to me|"
    r"převod|prevod|transfer between|to my |from my |"
    r"top-?up by|topup by|"
    r"revolut\*\*|card payment — revolut|merchant.?revolut)",
    re.IGNORECASE,
)
# "revolut" alone is a strong cross-institution signal on bank statements
_INSTITUTION_CROSS_RE = re.compile(
    r"\brevolut\b|\braiffeisen\b|\bsent from revolut\b",
    re.IGNORECASE,
)
_TRANSFERISH_RE = re.compile(
    r"\b(transfer|topup|top-up|withdrawal|incoming payment|outgoing|"
    r"cash top-up|cash withdrawal)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TransferMatchConfig:
    """Thresholds tuned for precision."""

    date_window_days: int = 3
    # Same-currency absolute tolerance (covers minor fee splits)
    amount_abs_tolerance: Decimal = Decimal("0.50")
    # Same-currency relative tolerance
    amount_rel_tolerance: Decimal = Decimal("0.002")  # 0.2%
    # Require high score to auto-link (0–100)
    min_auto_score: int = 70
    require_keyword_or_exact_amount: bool = True


@dataclass
class TransferMatchResult:
    transactions: list[Transaction]
    pairs_linked: int
    candidates_skipped: int


def _text_blob(tx: Transaction) -> str:
    """Narrative fields only — never include source_institution (avoids self-match)."""
    parts = [
        tx.merchant or "",
        tx.description or "",
        tx.original_description or "",
        tx.counterparty_name or "",
        tx.counterparty_account or "",
        tx.notes or "",
    ]
    return " ".join(parts)


def _has_strong_hint(tx: Transaction) -> bool:
    blob = _text_blob(tx)
    if _HINT_RE.search(blob):
        return True
    # Merchant explicitly Revolut on a bank statement = funding/withdrawal leg
    if (tx.merchant or "").strip().lower() == "revolut":
        return True
    # Cross-institution keywords in narrative (not the institution field itself)
    if (tx.source_institution or "").lower() == "raiffeisen" and re.search(
        r"\brevolut\b|sent from revolut",
        blob,
        re.I,
    ):
        return True
    if (tx.source_institution or "").lower() == "revolut" and re.search(
        r"\braiffeisen\b|own bank|to my bank|from \*",
        blob,
        re.I,
    ):
        return True
    return False


def _has_transferish(tx: Transaction) -> bool:
    return bool(_TRANSFERISH_RE.search(_text_blob(tx)))


def _amount_close(
    a: Decimal,
    b: Decimal,
    *,
    abs_tol: Decimal,
    rel_tol: Decimal,
) -> bool:
    """Compare absolute values of opposing legs."""
    aa, bb = abs(a), abs(b)
    if aa == 0 and bb == 0:
        return True
    diff = abs(aa - bb)
    if diff <= abs_tol:
        return True
    base = max(aa, bb)
    return base > 0 and (diff / base) <= rel_tol


def _score_pair(
    out_tx: Transaction,
    in_tx: Transaction,
    *,
    cfg: TransferMatchConfig,
) -> int | None:
    """
    Score a candidate outflow/inflow pair. Returns None if hard constraints fail.
    """
    if out_tx.account_id == in_tx.account_id:
        return None
    if out_tx.currency.upper() != in_tx.currency.upper():
        # v1: same currency only (FX legs left for manual / later phase)
        return None
    if out_tx.amount >= 0 or in_tx.amount <= 0:
        return None
    if out_tx.transfer_group_id is not None or in_tx.transfer_group_id is not None:
        return None
    if out_tx.archived or in_tx.archived:
        return None

    if not _amount_close(
        out_tx.amount,
        in_tx.amount,
        abs_tol=cfg.amount_abs_tolerance,
        rel_tol=cfg.amount_rel_tolerance,
    ):
        return None

    d_out = out_tx.booking_date
    d_in = in_tx.booking_date
    day_gap = abs((d_out - d_in).days)
    if day_gap > cfg.date_window_days:
        return None

    score = 40  # base for hard constraints passed
    exact = abs(out_tx.amount) == abs(in_tx.amount)

    # Exact amount match is strong
    if exact:
        score += 30
    else:
        score += 10

    if day_gap == 0:
        score += 15
    elif day_gap == 1:
        score += 10
    else:
        score += 5

    strong = _has_strong_hint(out_tx) or _has_strong_hint(in_tx)
    transferish = _has_transferish(out_tx) or _has_transferish(in_tx)
    if strong:
        score += 20
    elif transferish:
        score += 8

    # Already flagged on one side (from category rules) boosts confidence
    if out_tx.is_internal_transfer or in_tx.is_internal_transfer:
        score += 10

    # Cross-institution without any transfer signal is almost always coincidence
    different_institutions = (
        (out_tx.source_institution or "").lower()
        != (in_tx.source_institution or "").lower()
    )
    if different_institutions and not strong and not transferish:
        return None

    preflagged = out_tx.is_internal_transfer or in_tx.is_internal_transfer

    # Non-exact amounts (FX residue, fees) require a strong own-account hint.
    if not exact and not strong and not preflagged:
        return None

    # Precision gate: never auto-link on bare amount coincidence.
    # Need a strong own-account hint, a prior flag, or (exact amount + transfer-ish wording).
    if cfg.require_keyword_or_exact_amount:
        if not (strong or preflagged or (exact and transferish)):
            return None

    # Reject obvious merchant card spend vs random opposite-sign cash
    # (e.g. Spotify -185 vs Revolut FX +184).
    if not strong and not preflagged:
        out_merchant = (out_tx.merchant or "").strip().lower()
        in_merchant = (in_tx.merchant or "").strip().lower()
        card_merchants = {out_merchant, in_merchant} - {"", "revolut", "transfer"}
        if card_merchants and not transferish:
            return None

    return score


def match_internal_transfers(
    transactions: list[Transaction],
    *,
    config: TransferMatchConfig | None = None,
) -> TransferMatchResult:
    """
    Auto-detect high-confidence internal transfer pairs in a transaction list.

    Both legs get ``is_internal_transfer=True`` and a shared ``transfer_group_id``.
    Returns new Transaction instances (inputs are not mutated).
    """
    cfg = config or TransferMatchConfig()
    # Working copies keyed by id
    by_id: dict[UUID, Transaction] = {t.id: t.model_copy(deep=True) for t in transactions}
    order = list(by_id.keys())

    outflows = [t for t in by_id.values() if t.amount < 0 and not t.archived]
    inflows = [t for t in by_id.values() if t.amount > 0 and not t.archived]

    # Index inflows by currency for O(n·k) instead of O(n²)
    in_by_ccy: dict[str, list[Transaction]] = {}
    for i in inflows:
        in_by_ccy.setdefault(i.currency.upper(), []).append(i)

    candidates: list[tuple[int, UUID, UUID]] = []
    skipped = 0
    for o in outflows:
        for i in in_by_ccy.get(o.currency.upper(), ()):
            score = _score_pair(o, i, cfg=cfg)
            if score is None:
                continue
            if score < cfg.min_auto_score:
                skipped += 1
                continue
            candidates.append((score, o.id, i.id))

    # Highest score first; stable tie-break by date proximity handled in score
    candidates.sort(key=lambda x: (-x[0], str(x[1]), str(x[2])))

    used: set[UUID] = set()
    pairs = 0
    for score, oid, iid in candidates:
        if oid in used or iid in used:
            continue
        group = uuid4()
        o = by_id[oid]
        i = by_id[iid]
        by_id[oid] = o.model_copy(
            update={
                "is_internal_transfer": True,
                "transfer_group_id": group,
            }
        )
        by_id[iid] = i.model_copy(
            update={
                "is_internal_transfer": True,
                "transfer_group_id": group,
            }
        )
        used.add(oid)
        used.add(iid)
        pairs += 1

    # Preserve input order
    result_txs = [by_id[i] for i in order]
    return TransferMatchResult(
        transactions=result_txs,
        pairs_linked=pairs,
        candidates_skipped=skipped,
    )
