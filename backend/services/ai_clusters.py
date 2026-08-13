"""
AI-built categorize clusters for New ET Review.

Suggest-only. Never writes the ledger. No sandbox/heuristic fallback —
requires AI_ENABLED + XAI_API_KEY.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable
from uuid import UUID

from backend.config import Settings, get_settings
from backend.schema.models import Category, Transaction
from backend.services import ai_client, ai_quota
from backend.services.ai_categorize import (
    _category_catalog,
    amount_sign,
    is_blank_category,
)
from backend.services.ai_client import ChatResult, ChatTransport
from backend.sheets.repository import SheetsRepository

logger = logging.getLogger(__name__)

CLUSTER_KINDS = frozenset(
    {"vendor", "near_identical", "internal_transfer", "income", "fee", "other"}
)

_IBAN_RE = re.compile(
    r"\b(?:IBAN\s*)?[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b",
    re.I,
)
_LONG_DIGIT_RE = re.compile(r"\b\d{8,}\b")

SYSTEM_PROMPT = """You cluster residual bank transactions for a human to categorize.

You receive residual rows (id, date, merchant, short description, sign, currency,
rounded amount, institution) and allowed leaf categories (id, name, life_domain).

Return JSON only:
{"clusters":[{"title":"...","kind":"vendor|near_identical|internal_transfer|income|fee|other","transaction_ids":["..."],"category_id":"<uuid or empty>","confidence":0.0-1.0,"reason":"short","needs_human":false}]}

Rules:
- Build useful work piles. Prefer large obvious groups, identical/near vendors, then obvious pot-to-pot / internal transfers.
- Every transaction_id MUST be one of the ids you were given. Do not invent ids.
- A row may appear in at most one cluster.
- kind must be one of the enum values above.
- category_id MUST be an allowed category UUID when needs_human is false.
- For pot-to-pot / own-account / savings / me-to-me, use kind=internal_transfer and the Internal transfer category if present.
- If unsure, needs_human=true and omit category_id. Never use Other or Uncategorized.
- Do not invent categories. Do not include account numbers or personal data not in the input.
- Order clusters by how obvious/large they are (best first).
- Return at most 8 clusters. Skip leftovers. Do not try to cover every row.
"""

_Q2 = Decimal("0.01")


@dataclass
class ResidualRow:
    id: str
    booking_date: str
    merchant: str
    description: str
    sign: str
    currency: str
    amount: str
    institution: str


@dataclass
class ClusterSuggestion:
    title: str
    kind: str
    transaction_ids: list[str]
    category_id: str
    category_name: str
    confidence: float
    reason: str
    needs_human: bool
    sample_count: int
    cluster_key: str = ""


@dataclass
class ClusterResult:
    enabled: bool
    configured: bool
    model: str | None
    clusters: list[ClusterSuggestion] = field(default_factory=list)
    txs_considered: int = 0
    clusters_suggested: int = 0
    tokens_used: int = 0
    quota_used: int = 0
    quota_cap: int = 0
    message: str | None = None
    transactions: list[dict[str, Any]] = field(default_factory=list)


def _sanitize_text(s: str, *, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", (s or "").strip())
    text = _IBAN_RE.sub("[redacted]", text)
    text = _LONG_DIGIT_RE.sub("[redacted]", text)
    return text[:limit]


def _round_abs(amount: Decimal) -> str:
    return str(abs(amount).quantize(_Q2, rounding=ROUND_HALF_UP))


def canonical_tx_id(raw: object) -> str | None:
    """Normalize Grok / client ids to hyphenated lowercase UUID strings."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return str(UUID(text))
    except ValueError:
        return None


def select_residual_rows(
    transactions: list[Transaction],
    categories: list[Category],
    *,
    limit: int,
    date_from: str = "",
    date_to: str = "",
    exclude_ids: set[str] | None = None,
) -> list[ResidualRow]:
    cat_by_id = {c.id: c for c in categories if not c.archived}
    df = (date_from or "").strip()[:10]
    dt = (date_to or "").strip()[:10]
    skip = {canonical_tx_id(x) or str(x) for x in (exclude_ids or set()) if x}
    scored: list[tuple[Decimal, str, Transaction]] = []
    for t in transactions:
        if t.archived or t.is_internal_transfer:
            continue
        if canonical_tx_id(t.id) in skip or str(t.id) in skip:
            continue
        if not is_blank_category(t, cat_by_id):
            continue
        bd = t.booking_date
        bd_s = bd.isoformat() if hasattr(bd, "isoformat") else str(bd)[:10]
        if df and bd_s < df:
            continue
        if dt and bd_s > dt:
            continue
        amt = t.amount if isinstance(t.amount, Decimal) else Decimal(str(t.amount or "0"))
        scored.append((abs(amt), bd_s, t))
    scored.sort(key=lambda x: (-x[0], x[1]), reverse=False)
    # largest first, then newest date among ties already in sort? We want abs desc, date desc
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    out: list[ResidualRow] = []
    for _mag, bd_s, t in scored[: max(0, limit)]:
        amt = t.amount if isinstance(t.amount, Decimal) else Decimal(str(t.amount or "0"))
        merchant = _sanitize_text(t.merchant or "", limit=64)
        desc = _sanitize_text(t.description or t.original_description or "", limit=80)
        out.append(
            ResidualRow(
                id=str(t.id),
                booking_date=bd_s,
                merchant=merchant,
                description=desc if desc.lower() != merchant.lower() else "",
                sign=amount_sign(amt),
                currency=(t.currency or "USD").upper(),
                amount=_round_abs(amt),
                institution=_sanitize_text(t.source_institution or "", limit=40),
            )
        )
    return out


def build_user_payload(rows: list[ResidualRow], catalog: list[dict[str, str]]) -> str:
    payload = {
        "transactions": [
            {
                "id": r.id,
                "date": r.booking_date,
                "merchant": r.merchant,
                "description": r.description,
                "sign": r.sign,
                "currency": r.currency,
                "amount": r.amount,
                "institution": r.institution,
            }
            for r in rows
        ],
        "categories": catalog,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def validate_clusters(
    raw: dict[str, Any],
    sent_ids: set[str],
    categories: list[Category],
) -> list[ClusterSuggestion]:
    allowed = {row["id"]: row for row in _category_catalog(categories)}
    items = raw.get("clusters")
    if not isinstance(items, list):
        return []
    sent_canon = {canonical_tx_id(s) or s for s in sent_ids}
    seen_tx: set[str] = set()
    out: list[ClusterSuggestion] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "other").strip().lower()
        if kind not in CLUSTER_KINDS:
            continue
        raw_ids = item.get("transaction_ids")
        if not isinstance(raw_ids, list):
            continue
        ids: list[str] = []
        for raw_id in raw_ids:
            tid = canonical_tx_id(raw_id) or str(raw_id or "").strip()
            if not tid or tid not in sent_canon or tid in seen_tx:
                continue
            ids.append(tid)
            seen_tx.add(tid)
        if not ids:
            continue
        needs_human = bool(item.get("needs_human"))
        cat_id = str(item.get("category_id") or "").strip()
        cat_name = ""
        if cat_id and cat_id in allowed:
            cat_name = allowed[cat_id]["name"]
        else:
            cat_id = ""
            needs_human = True
        try:
            conf = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        title = str(item.get("title") or "").strip()[:80] or f"Cluster {i + 1}"
        reason = str(item.get("reason") or "").strip()[:240]
        out.append(
            ClusterSuggestion(
                title=title,
                kind=kind,
                transaction_ids=ids,
                category_id=cat_id,
                category_name=cat_name,
                confidence=conf,
                reason=reason,
                needs_human=needs_human,
                sample_count=len(ids),
                cluster_key=f"c{i}-{ids[0][:8]}",
            )
        )
    return out


def _empty(
    *,
    enabled: bool,
    configured: bool,
    model: str | None,
    settings: Settings,
    principal: str,
    message: str,
    txs_considered: int = 0,
) -> ClusterResult:
    snap = ai_quota.snapshot(
        principal, cap=settings.ai_daily_token_cap, global_cap=settings.ai_global_daily_token_cap
    )
    return ClusterResult(
        enabled=enabled,
        configured=configured,
        model=model,
        message=message,
        txs_considered=txs_considered,
        quota_used=snap.used,
        quota_cap=snap.cap,
    )


def suggest_clusters(
    repo: SheetsRepository,
    *,
    principal: str,
    settings: Settings | None = None,
    limit: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    exclude_transaction_ids: list[str] | None = None,
    transport: ChatTransport | None = None,
    chat_fn: Callable[..., ChatResult] | None = None,
) -> ClusterResult:
    """Ask Grok to pile residual txs. Never writes. No heuristic fallback."""
    s = settings or get_settings()
    if not s.ai_enabled:
        return _empty(
            enabled=False,
            configured=False,
            model=None,
            settings=s,
            principal=principal,
            message="AI assist is disabled (set AI_ENABLED=true).",
        )
    if not s.ai_configured:
        return _empty(
            enabled=True,
            configured=False,
            model=None,
            settings=s,
            principal=principal,
            message="AI assist enabled but XAI_API_KEY is not set.",
        )

    categories = [c for c in repo.list_rows("Categories") if isinstance(c, Category)]
    txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction)]
    # Keep the first batch small: grok-4.5 can reason longer than 60s on 60 rows.
    default_n = min(20, max(12, s.ai_max_merchants_per_request // 2 or 12))
    max_n = limit if limit is not None else default_n
    max_n = max(8, min(max_n, 40))

    exclude = {
        canonical_tx_id(x) or str(x)
        for x in (exclude_transaction_ids or [])
        if x
    }
    rows = select_residual_rows(
        txs,
        categories,
        limit=max_n,
        date_from=date_from or "",
        date_to=date_to or "",
        exclude_ids=exclude,
    )
    if not rows:
        return _empty(
            enabled=True,
            configured=True,
            model=s.ai_model,
            settings=s,
            principal=principal,
            message="No residual transactions to cluster.",
            txs_considered=0,
        )

    catalog = _category_catalog(categories)
    if not catalog:
        return _empty(
            enabled=True,
            configured=True,
            model=s.ai_model,
            settings=s,
            principal=principal,
            message="No assignable leaf categories configured.",
            txs_considered=len(rows),
        )

    user_payload = build_user_payload(rows, catalog)
    timeout = max(float(s.ai_request_timeout_seconds), 180.0)
    logger.info(
        "AI cluster request txs=%s payload_chars=%s timeout_s=%.0f model=%s",
        len(rows),
        len(user_payload),
        timeout,
        s.ai_model,
    )
    estimate = max(900, (len(SYSTEM_PROMPT) + len(user_payload)) // 3 + 500)
    try:
        ai_quota.check_and_reserve(
            principal,
            estimate,
            cap=s.ai_daily_token_cap,
            global_cap=s.ai_global_daily_token_cap,
        )
    except ValueError as exc:
        return _empty(
            enabled=True,
            configured=True,
            model=s.ai_model,
            settings=s,
            principal=principal,
            message=str(exc),
            txs_considered=len(rows),
        )

    runner = chat_fn or ai_client.chat_json
    try:
        result = runner(
            api_key=s.xai_api_key,
            base_url=s.xai_base_url,
            model=s.ai_model,
            system=SYSTEM_PROMPT,
            user=user_payload,
            timeout=timeout,
            transport=transport,
        )
    except Exception as exc:
        ai_quota.settle(principal, estimate, 0)
        logger.warning("AI cluster call failed: %s", type(exc).__name__)
        return _empty(
            enabled=True,
            configured=True,
            model=s.ai_model,
            settings=s,
            principal=principal,
            message=str(exc) if str(exc) else "Grok request failed",
            txs_considered=len(rows),
        )

    actual = result.total_tokens or (result.prompt_tokens + result.completion_tokens)
    if actual <= 0:
        actual = estimate
    ai_quota.settle(principal, estimate, actual)

    try:
        raw = ai_client.parse_json_object(result.content)
        clusters = validate_clusters(raw, {r.id for r in rows}, categories)
        msg = None if clusters else "Grok returned no valid clusters. Try again."
    except Exception:
        logger.warning("AI cluster response parse/validate failed")
        clusters = []
        msg = "Grok returned unusable clusters. Try again."

    used_ids = {tid for c in clusters for tid in c.transaction_ids}
    tx_dumps: list[dict[str, Any]] = []
    for t in txs:
        if str(t.id) in used_ids:
            tx_dumps.append(t.model_dump(mode="json"))

    snap = ai_quota.snapshot(
        principal, cap=s.ai_daily_token_cap, global_cap=s.ai_global_daily_token_cap
    )
    return ClusterResult(
        enabled=True,
        configured=True,
        model=result.model or s.ai_model,
        clusters=clusters,
        txs_considered=len(rows),
        clusters_suggested=len(clusters),
        tokens_used=actual,
        quota_used=snap.used,
        quota_cap=snap.cap,
        message=msg,
        transactions=tx_dumps,
    )


def cluster_to_dict(c: ClusterSuggestion) -> dict[str, Any]:
    return {
        "cluster_key": c.cluster_key,
        "title": c.title,
        "kind": c.kind,
        "transaction_ids": c.transaction_ids,
        "category_id": c.category_id,
        "category_name": c.category_name,
        "confidence": c.confidence,
        "reason": c.reason,
        "needs_human": c.needs_human,
        "sample_count": c.sample_count,
    }
