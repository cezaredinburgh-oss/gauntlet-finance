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

SYSTEM_PROMPT = """You cluster residual bank transactions for a human to categorize quickly.

You receive residual rows (id, date, merchant, short description, sign, currency,
rounded amount, institution) and allowed leaf categories (id, name, life_domain).
Rows are already biased toward repeat vendors — use that.

Return JSON only:
{"clusters":[{"title":"...","kind":"vendor|near_identical|internal_transfer|income|fee|other","transaction_ids":["..."],"category_id":"<uuid or empty>","confidence":0.0-1.0,"reason":"short","needs_human":false}]}

Priority (highest first):
1. Same merchant / same vendor text appearing many times (kind=vendor). These are the easy wins.
2. Near-identical description or amount repeats (kind=near_identical).
3. Obvious pot-to-pot / own-account / savings / me-to-me (kind=internal_transfer).
4. Repeat fees / ATM (kind=fee).
5. Repeat uncategorized income (kind=income).

Do NOT lead with one-off large amounts. A single 200k transfer is worse than 12 Lidl groceries.
Omit unique large outliers unless nothing else is clusterable.

Rules:
- Every transaction_id MUST be copied exactly from the input ids. Do not invent or shorten ids.
- A row may appear in at most one cluster.
- kind must be one of the enum values above.
- category_id MUST be an allowed category UUID when needs_human is false.
- For pot-to-pot, use kind=internal_transfer and the Internal transfer category if present.
- If unsure, needs_human=true and omit category_id. Never use Other or Uncategorized.
- Do not invent categories. Do not include account numbers or personal data not in the input.
- Order clusters by how many rows they save the user (count first), not by amount.
- Return at most 8 clusters. Skip leftovers.
"""

_Q2 = Decimal("0.01")

_TRANSFER_KEY = re.compile(
    r"\b(revolut|raiffeisen|transfer|top-?up|topup|own account|savings|me2me)\b",
    re.I,
)

ASK_SYSTEM_PROMPT = """You find residual bank transactions that match the user's request.

The user asked a question (e.g. "grocery related transactions").
You receive residual rows that were pre-filtered for relevance, plus allowed leaf categories.

Return JSON only:
{"reply":"one short sentence","clusters":[{"title":"...","kind":"vendor|near_identical|internal_transfer|income|fee|other","transaction_ids":["..."],"category_id":"<uuid or empty>","confidence":0.0-1.0,"reason":"short","needs_human":false}]}

Rules:
- Only use transaction ids from the input. Copy them exactly.
- Prefer many similar everyday spend rows (groceries, coffee, transit) over one-off large transfers.
- If the user asked for groceries/food, pick supermarket / grocery / food merchants.
- category_id must be an allowed UUID, or set needs_human=true.
- reply: one sentence describing what you found (counts, not amounts unless asked).
- At most 8 clusters. A row in at most one cluster.
"""

_QUERY_HINTS: dict[str, tuple[str, ...]] = {
    "grocer": ("lidl", "tesco", "albert", "kaufland", "billa", "spar", "aldi", "penny", "supermarket", "grocery", "groceries", "potravin"),
    "food": ("lidl", "tesco", "albert", "restaurant", "pizza", "kebab", "mcdonald", "kfc", "cafe", "coffee"),
    "coffee": ("starbucks", "costa", "cafe", "coffee", "nespresso"),
    "transport": ("uber", "bolt", "pid", "dpp", "pid litacka", "fuel", "shell", "omv", "benzina"),
    "rent": ("rent", "najem", "landlord"),
    "transfer": ("transfer", "top-up", "topup", "revolut", "raiffeisen"),
}


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
    reply: str = ""
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

    # Easy clusters first: repeat vendor/description, not largest one-off amounts.
    groups: dict[str, list[tuple[Decimal, str, Transaction]]] = {}
    for mag, bd_s, t in scored:
        merchant = _sanitize_text(t.merchant or "", limit=64)
        desc = _sanitize_text(t.description or t.original_description or "", limit=80)
        if merchant:
            key = f"m:{merchant.lower()}"
        elif desc:
            key = f"d:{desc[:48].lower()}"
        else:
            key = f"id:{t.id}"
        groups.setdefault(key, []).append((mag, bd_s, t))

    def _group_rank(k: str) -> tuple[int, int, str]:
        transferish = 1 if _TRANSFER_KEY.search(k) else 0
        return (transferish, -len(groups[k]), max(x[1] for x in groups[k]))

    ranked_keys = sorted(groups, key=_group_rank)
    picked: list[tuple[Decimal, str, Transaction]] = []
    per_group = 8

    def _take(predicate) -> None:
        for key in ranked_keys:
            if len(picked) >= limit:
                return
            bucket = groups[key]
            if not predicate(key, bucket):
                continue
            bucket.sort(key=lambda x: x[1], reverse=True)
            n = per_group if len(bucket) >= 2 else 1
            picked.extend(bucket[:n])

    _take(lambda k, b: len(b) >= 2 and not _TRANSFER_KEY.search(k))
    _take(lambda k, b: len(b) >= 2 and bool(_TRANSFER_KEY.search(k)))
    _take(lambda k, b: len(b) < 2 and not _TRANSFER_KEY.search(k))
    _take(lambda k, b: len(b) < 2)

    out: list[ResidualRow] = []
    for _mag, bd_s, t in picked[: max(0, limit)]:
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


def query_tokens(question: str) -> list[str]:
    raw = re.findall(r"[a-zA-Z0-9]{3,}", (question or "").lower())
    extra: list[str] = []
    blob = " ".join(raw)
    for needle, hints in _QUERY_HINTS.items():
        if needle in blob or any(h in blob for h in hints):
            extra.extend(hints)
            extra.append(needle)
    out: list[str] = []
    seen: set[str] = set()
    for tok in [*raw, *extra]:
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def select_residual_for_query(
    transactions: list[Transaction],
    categories: list[Category],
    question: str,
    *,
    limit: int,
    date_from: str = "",
    date_to: str = "",
    exclude_ids: set[str] | None = None,
) -> list[ResidualRow]:
    """Residual rows ranked by query/token overlap, not amount."""
    tokens = query_tokens(question)
    cat_by_id = {c.id: c for c in categories if not c.archived}
    df = (date_from or "").strip()[:10]
    dt = (date_to or "").strip()[:10]
    skip = {canonical_tx_id(x) or str(x) for x in (exclude_ids or set()) if x}
    scored: list[tuple[int, str, Transaction]] = []
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
        blob = " ".join(
            [
                (t.merchant or ""),
                (t.description or ""),
                (t.original_description or ""),
            ]
        ).lower()
        hits = sum(1 for tok in tokens if tok in blob) if tokens else 0
        scored.append((hits, bd_s, t))
    scored.sort(key=lambda x: (-x[0], x[1]), reverse=False)
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    # Prefer any positive hit; keep a few zero-hit only if nothing matched
    hits_only = [s for s in scored if s[0] > 0]
    pool = hits_only if hits_only else scored
    out: list[ResidualRow] = []
    for _hits, bd_s, t in pool[: max(0, limit)]:
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
    # Repeat-vendor slice, still small enough for grok-4.5 latency.
    default_n = min(32, max(16, s.ai_max_merchants_per_request))
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


def ask_clusters(
    repo: SheetsRepository,
    *,
    principal: str,
    question: str,
    settings: Settings | None = None,
    limit: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    exclude_transaction_ids: list[str] | None = None,
    transport: ChatTransport | None = None,
    chat_fn: Callable[..., ChatResult] | None = None,
) -> ClusterResult:
    """Natural-language residual search. Suggest-only. No heuristic fallback."""
    s = settings or get_settings()
    q = (question or "").strip()
    if not q:
        return _empty(
            enabled=True,
            configured=bool(s.ai_configured),
            model=s.ai_model if s.ai_configured else None,
            settings=s,
            principal=principal,
            message="Type what you want to find (e.g. grocery related transactions).",
        )
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
    max_n = limit if limit is not None else 40
    max_n = max(12, min(max_n, 60))
    exclude = {
        canonical_tx_id(x) or str(x)
        for x in (exclude_transaction_ids or [])
        if x
    }
    rows = select_residual_for_query(
        txs,
        categories,
        q,
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
            message="No residual transactions matched that request.",
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

    payload = {
        "question": q[:400],
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
    user_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    timeout = max(float(s.ai_request_timeout_seconds), 180.0)
    logger.info(
        "AI ask request q_len=%s txs=%s payload_chars=%s",
        len(q),
        len(rows),
        len(user_payload),
    )
    estimate = max(900, (len(ASK_SYSTEM_PROMPT) + len(user_payload)) // 3 + 500)
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
            system=ASK_SYSTEM_PROMPT,
            user=user_payload,
            timeout=timeout,
            transport=transport,
        )
    except Exception as exc:
        ai_quota.settle(principal, estimate, 0)
        logger.warning("AI ask call failed: %s", type(exc).__name__)
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

    reply = ""
    try:
        raw = ai_client.parse_json_object(result.content)
        reply = str(raw.get("reply") or "").strip()[:400]
        clusters = validate_clusters(raw, {r.id for r in rows}, categories)
        msg = None if clusters else (reply or "No matching residual rows in that ask.")
    except Exception:
        logger.warning("AI ask response parse/validate failed")
        clusters = []
        msg = "Grok returned an unusable answer. Try a simpler ask."

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
        reply=reply,
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


PRESET_KINDS = frozenset({"top_vendors", "internal", "fees", "income"})

_FEE_HINT = re.compile(
    r"\b(fee|charge|atm|cash withdraw|v[yý]b[eě]r|poplatek|commission|fx fee)\b",
    re.I,
)


def _vendor_bucket_key(t: Transaction) -> tuple[str, str]:
    merchant = _sanitize_text(t.merchant or "", limit=64)
    desc = _sanitize_text(t.description or t.original_description or "", limit=80)
    if merchant:
        return f"m:{merchant.lower()}", merchant
    if desc:
        return f"d:{desc[:48].lower()}", desc[:48]
    return f"id:{t.id}", "(no label)"


def _residual_transactions(
    transactions: list[Transaction],
    categories: list[Category],
    *,
    date_from: str = "",
    date_to: str = "",
    exclude_ids: set[str] | None = None,
) -> list[Transaction]:
    cat_by_id = {c.id: c for c in categories if not c.archived}
    df = (date_from or "").strip()[:10]
    dt = (date_to or "").strip()[:10]
    skip = {canonical_tx_id(x) or str(x) for x in (exclude_ids or set()) if x}
    out: list[Transaction] = []
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
        out.append(t)
    return out


def build_preset_piles(
    transactions: list[Transaction],
    categories: list[Category],
    kind: str,
    *,
    date_from: str = "",
    date_to: str = "",
    exclude_ids: set[str] | None = None,
) -> tuple[list[ClusterSuggestion], list[Transaction]]:
    """Deterministic easy-win piles. No Grok."""
    from backend.schema.default_categories import CAT_BANK_FEES, CAT_INTERNAL
    from backend.services.alerts import looks_like_transfer_narrative

    kind = (kind or "").strip().lower()
    if kind not in PRESET_KINDS:
        raise ValueError(f"unknown preset kind: {kind}")
    residuals = _residual_transactions(
        transactions,
        categories,
        date_from=date_from,
        date_to=date_to,
        exclude_ids=exclude_ids,
    )
    cat_name = {str(c.id): c.name for c in categories if not c.archived}
    piles: list[ClusterSuggestion] = []
    used: list[Transaction] = []

    if kind == "top_vendors":
        buckets: dict[str, list[Transaction]] = {}
        labels: dict[str, str] = {}
        for t in residuals:
            key, label = _vendor_bucket_key(t)
            buckets.setdefault(key, []).append(t)
            labels[key] = label
        ranked = sorted(buckets.items(), key=lambda kv: (-len(kv[1]), labels[kv[0]].lower()))
        for i, (key, bucket) in enumerate(ranked[:5]):
            ids = [str(t.id) for t in bucket]
            piles.append(
                ClusterSuggestion(
                    title=f"{labels[key]} ({len(bucket)} tx)",
                    kind="vendor",
                    transaction_ids=ids,
                    category_id="",
                    category_name="",
                    confidence=0.0,
                    reason="Most residual rows for this vendor",
                    needs_human=True,
                    sample_count=len(ids),
                    cluster_key=f"preset-vendor-{i}",
                )
            )
            used.extend(bucket)
    elif kind == "internal":
        hits = [t for t in residuals if looks_like_transfer_narrative(t)]
        if hits:
            piles.append(
                ClusterSuggestion(
                    title=f"Suspected internal transfers ({len(hits)} tx)",
                    kind="internal_transfer",
                    transaction_ids=[str(t.id) for t in hits],
                    category_id=str(CAT_INTERNAL),
                    category_name=cat_name.get(str(CAT_INTERNAL), "Internal transfer"),
                    confidence=0.7,
                    reason="Transfer-like wording, not yet flagged internal",
                    needs_human=False,
                    sample_count=len(hits),
                    cluster_key="preset-internal",
                )
            )
            used.extend(hits)
    elif kind == "fees":
        hits = []
        for t in residuals:
            blob = " ".join(
                filter(None, [t.merchant, t.description, t.original_description])
            )
            if _FEE_HINT.search(blob or ""):
                hits.append(t)
        if hits:
            piles.append(
                ClusterSuggestion(
                    title=f"Fees / ATM ({len(hits)} tx)",
                    kind="fee",
                    transaction_ids=[str(t.id) for t in hits],
                    category_id=str(CAT_BANK_FEES),
                    category_name=cat_name.get(str(CAT_BANK_FEES), "Bank fees"),
                    confidence=0.65,
                    reason="Fee / ATM / withdrawal wording",
                    needs_human=False,
                    sample_count=len(hits),
                    cluster_key="preset-fees",
                )
            )
            used.extend(hits)
    elif kind == "income":
        hits = [
            t
            for t in residuals
            if (t.amount if isinstance(t.amount, Decimal) else Decimal(str(t.amount or "0")))
            > 0
        ]
        if hits:
            piles.append(
                ClusterSuggestion(
                    title=f"Uncategorized income ({len(hits)} tx)",
                    kind="income",
                    transaction_ids=[str(t.id) for t in hits],
                    category_id="",
                    category_name="",
                    confidence=0.0,
                    reason="Positive residual amounts",
                    needs_human=True,
                    sample_count=len(hits),
                    cluster_key="preset-income",
                )
            )
            used.extend(hits)

    return piles, used


def preset_piles(
    repo: SheetsRepository,
    *,
    kind: str,
    date_from: str = "",
    date_to: str = "",
    exclude_transaction_ids: list[str] | None = None,
) -> ClusterResult:
    categories = [c for c in repo.list_rows("Categories") if isinstance(c, Category)]
    txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction)]
    exclude = {
        canonical_tx_id(x) or str(x)
        for x in (exclude_transaction_ids or [])
        if x
    }
    piles, used = build_preset_piles(
        txs,
        categories,
        kind,
        date_from=date_from,
        date_to=date_to,
        exclude_ids=exclude,
    )
    used_ids = {str(t.id) for t in used}
    tx_dumps = [t.model_dump(mode="json") for t in used if str(t.id) in used_ids]
    return ClusterResult(
        enabled=True,
        configured=True,
        model=None,
        clusters=piles,
        txs_considered=len(used),
        clusters_suggested=len(piles),
        tokens_used=0,
        quota_used=0,
        quota_cap=0,
        message=None if piles else "No residual rows matched that shortcut.",
        transactions=tx_dumps,
    )
