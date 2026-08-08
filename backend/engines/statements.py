"""
StatementFiles management and cross-row deduplication helpers.

Side effects only through an injected :class:`SheetsRepository`.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence
from uuid import UUID, uuid4

from backend.common.hashing import sha256_hex
from backend.common.timeutil import utc_now
from backend.schema.models import (
    InvestmentEvent,
    StatementFile,
    StatementFileStatus,
    Transaction,
)
from backend.sheets.repository import SheetsRepository


def norm_decimal_for_identity(value) -> str:
    """Stable decimal string (avoids 14000 vs 14000.00 sheet round-trips)."""
    if value is None:
        return "0"
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    s = format(d.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def event_datetime_iso(event_datetime: datetime | None) -> str:
    """
    Identity timestamp matching Sheets wire format (second resolution, UTC Z).

    Google Sheets encode drops microseconds via
    ``strftime("%Y-%m-%dT%H:%M:%SZ")``. Soft keys and external_id digests must
    use the same resolution so soft-only ledger rows still match re-parses.
    """
    if event_datetime is None:
        return ""
    dt = event_datetime
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def revolut_event_external_id(
    *,
    event_type: str,
    ticker: str | None,
    event_datetime: datetime | None,
    quantity,
    value_native,
    fees_native,
    currency: str | None,
) -> str:
    """
    Deterministic investment-event external_id for Revolut crypto/stocks.

    Format: ``ext:Revolut:{sha256(type|symbol|datetime_iso|qty|value|fees|ccy)[:24]}``
    Uses the same decimal + second-resolution datetime normalization as soft keys.
    """
    blob = "|".join(
        [
            (event_type or "").strip(),
            (ticker or "").strip(),
            event_datetime_iso(event_datetime),
            norm_decimal_for_identity(quantity),
            norm_decimal_for_identity(value_native),
            norm_decimal_for_identity(fees_native if fees_native is not None else 0),
            (currency or "").strip().upper(),
        ]
    )
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]
    return f"ext:Revolut:{digest}"


def _is_revolut_source(source: str | None) -> bool:
    return (source or "").strip().lower() == "revolut"


# Revolut expenses store wall-clock times in notes (date columns are date-only).
_NOTE_COMPLETED_RE = re.compile(r"completed=([^\s|]+)", re.IGNORECASE)
_NOTE_STARTED_RE = re.compile(r"started=([^\s|]+)", re.IGNORECASE)


def normalize_note_timestamp(raw: str | None) -> str:
    """Parse a notes timestamp token to second-resolution UTC Z (Sheets-safe)."""
    if raw is None or not str(raw).strip():
        return ""
    t = str(raw).strip()
    try:
        if t.endswith("Z") and "T" in t:
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        return event_datetime_iso(dt)
    except (TypeError, ValueError):
        return str(raw).strip()


def wall_times_from_tx_notes(notes: str | None) -> tuple[str, str]:
    """
    Extract completed=/started= wall times from Revolut expense notes.

    Returns (completed_iso_z, started_iso_z); empty strings when absent.
    """
    if not notes:
        return "", ""
    completed = ""
    started = ""
    m = _NOTE_COMPLETED_RE.search(notes)
    if m:
        completed = normalize_note_timestamp(m.group(1))
    m = _NOTE_STARTED_RE.search(notes)
    if m:
        started = normalize_note_timestamp(m.group(1))
    return completed, started


def collapse_events_by_identity(
    events: Sequence[InvestmentEvent],
) -> tuple[list[InvestmentEvent], int]:
    """
    Collapse duplicates using the same soft∪hard key union as ``dedupe_events``.

    Builds undirected connected components: events that share any identity key
    are the same logical trade. Keeps earliest ``created_at`` then lowest id.
    Returns (kept_rows, removed_count).
    """
    items = list(events)
    n = len(items)
    if n == 0:
        return [], 0

    parent = list(range(n))
    rank = [0] * n

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri == rj:
            return
        if rank[ri] < rank[rj]:
            parent[ri] = rj
        elif rank[ri] > rank[rj]:
            parent[rj] = ri
        else:
            parent[rj] = ri
            rank[ri] += 1

    key_first: dict[str, int] = {}
    for i, ev in enumerate(items):
        for k in StatementService._event_keys(ev):
            if k in key_first:
                union(i, key_first[k])
            else:
                key_first[k] = i

    groups: dict[int, list[InvestmentEvent]] = defaultdict(list)
    for i, ev in enumerate(items):
        groups[find(i)].append(ev)

    keep: list[InvestmentEvent] = []
    removed = 0
    for rows in groups.values():
        rows_sorted = sorted(rows, key=lambda x: (x.created_at, str(x.id)))
        keep.append(rows_sorted[0])
        removed += len(rows_sorted) - 1
    # Stable output order by created_at
    keep.sort(key=lambda x: (x.created_at, str(x.id)))
    return keep, removed


@dataclass
class DedupeResult:
    transactions: list[Transaction]
    investment_events: list[InvestmentEvent]
    dropped_transactions: int
    dropped_events: int


@dataclass
class RegisterStatementResult:
    status: str  # "new" | "duplicate"
    statement: StatementFile
    content_sha256: str


class StatementService:
    """Idempotent statement registration + in-memory/repo-backed dedupe."""

    def __init__(self, repo: SheetsRepository) -> None:
        self.repo = repo

    def content_hash(self, file_bytes: bytes) -> str:
        return sha256_hex(file_bytes)

    def find_by_hash(self, content_sha256: str) -> StatementFile | None:
        return self.repo.find_statement_by_hash(content_sha256)

    # Statuses that permanently gate re-upload of the same SHA-256.
    # PENDING/ERROR never block — a failed or abandoned import must be retriable.
    _BLOCKING_STATUSES = frozenset(
        {
            StatementFileStatus.IMPORTED,
            StatementFileStatus.SKIPPED_DUPLICATE,
        }
    )

    def is_duplicate(self, content_sha256: str) -> bool:
        """True only when this content was fully imported (or skipped as duplicate).

        PENDING (crash mid-import) and ERROR (explicit failure) do **not** block
        a retry. Row-level dedupe handles any partial ledger writes from the
        previous attempt.
        """
        row = self.find_by_hash(content_sha256)
        if row is None or row.archived:
            return False
        return row.status in self._BLOCKING_STATUSES

    def register_statement(
        self,
        *,
        filename: str,
        file_bytes: bytes,
        institution: str,
        row_count: int,
        parser_key: str | None,
        status: StatementFileStatus = StatementFileStatus.PENDING,
        now: datetime | None = None,
        statement_id: UUID | None = None,
    ) -> RegisterStatementResult:
        """
        Create a StatementFiles row unless the content hash already exists.

        On successful prior import, returns the existing row with status
        ``duplicate`` (does not write a second row). PENDING/ERROR rows are
        reset and retried so a rate-limit failure cannot lock the file out.
        """
        ts = now or utc_now()
        h = self.content_hash(file_bytes)
        existing = self.find_by_hash(h)
        if existing is not None and existing.status in self._BLOCKING_STATUSES:
            return RegisterStatementResult(
                status="duplicate",
                statement=existing,
                content_sha256=h,
            )

        if existing is not None:
            # Retry same file after a failed / abandoned import
            row = existing.model_copy(
                update={
                    "original_filename": filename,
                    "uploaded_at": ts,
                    "institution": institution,
                    "row_count": row_count,
                    "parser_key": parser_key,
                    "status": status,
                    "notes": None,
                    "updated_at": ts,
                    "archived": False,
                }
            )
        else:
            row = StatementFile(
                id=statement_id or uuid4(),
                original_filename=filename,
                uploaded_at=ts,
                content_sha256=h,
                institution=institution,
                row_count=row_count,
                parser_key=parser_key,
                status=status,
                created_at=ts,
                updated_at=ts,
            )
        self.repo.upsert_rows("StatementFiles", [row])
        return RegisterStatementResult(
            status="new",
            statement=row,
            content_sha256=h,
        )

    def mark_status(
        self,
        statement_id: UUID,
        status: StatementFileStatus,
        *,
        notes: str | None = None,
        now: datetime | None = None,
    ) -> StatementFile | None:
        row = self.repo.get_by_id("StatementFiles", statement_id)
        if row is None or not isinstance(row, StatementFile):
            return None
        ts = now or utc_now()
        updates: dict = {"status": status, "updated_at": ts}
        if notes is not None:
            updates["notes"] = notes
        updated = row.model_copy(update=updates)
        self.repo.upsert_rows("StatementFiles", [updated])
        return updated

    def mark_imported(
        self,
        statement_id: UUID,
        *,
        row_count: int | None = None,
        now: datetime | None = None,
    ) -> StatementFile | None:
        row = self.repo.get_by_id("StatementFiles", statement_id)
        if row is None or not isinstance(row, StatementFile):
            return None
        ts = now or utc_now()
        updates: dict = {
            "status": StatementFileStatus.IMPORTED,
            "updated_at": ts,
        }
        if row_count is not None:
            updates["row_count"] = row_count
        updated = row.model_copy(update=updates)
        self.repo.upsert_rows("StatementFiles", [updated])
        return updated

    def mark_duplicate_skip(
        self,
        statement_id: UUID,
        *,
        now: datetime | None = None,
    ) -> StatementFile | None:
        return self.mark_status(
            statement_id,
            StatementFileStatus.SKIPPED_DUPLICATE,
            now=now,
        )

    # ------------------------------------------------------------------
    # Row-level deduplication (pure)
    # ------------------------------------------------------------------

    @staticmethod
    def dedupe_transactions(
        existing: Iterable[Transaction],
        incoming: Iterable[Transaction],
    ) -> DedupeResult:
        """
        Drop only true duplicates among incoming rows.

        Rules (precision-preserving):
        1. Non-Revolut hard ``external_id`` (e.g. Raiffeisen): hard only — same-day
           same-amount rows with different IDs are **kept**.
        2. Revolut with ``external_id``: soft∪hard. Soft includes wall-clock
           completed/started from notes so same-day FX/exchanges stay distinct,
           while Balance-free vs Balance-including ``rev:`` hashes still soft-match.
        3. No external_id: soft only (date, times from notes, amount, fee, …).
        """
        keys: set[str] = set()
        for tx in existing:
            keys |= StatementService._tx_keys(tx)

        kept: list[Transaction] = []
        dropped = 0
        for tx in incoming:
            kset = StatementService._tx_keys(tx)
            if kset & keys:
                dropped += 1
                continue
            kept.append(tx)
            keys |= kset

        return DedupeResult(
            transactions=kept,
            investment_events=[],
            dropped_transactions=dropped,
            dropped_events=0,
        )

    @staticmethod
    def dedupe_events(
        existing: Iterable[InvestmentEvent],
        incoming: Iterable[InvestmentEvent],
    ) -> DedupeResult:
        keys: set[str] = set()
        for ev in existing:
            keys |= StatementService._event_keys(ev)

        kept: list[InvestmentEvent] = []
        dropped = 0
        for ev in incoming:
            kset = StatementService._event_keys(ev)
            if kset & keys:
                dropped += 1
                continue
            kept.append(ev)
            keys |= kset

        return DedupeResult(
            transactions=[],
            investment_events=kept,
            dropped_transactions=0,
            dropped_events=dropped,
        )

    @staticmethod
    def _tx_hard_key(tx: Transaction) -> str | None:
        """Stable identity when the institution provides a unique transaction id."""
        if not tx.external_id:
            return None
        # Intentionally omit account_id — re-imports may remap accounts.
        return f"ext:{tx.source_institution}:{tx.external_id}"

    @staticmethod
    def _norm_decimal(value) -> str:
        """Stable decimal string (avoids 14000 vs 14000.00 sheet round-trips)."""
        return norm_decimal_for_identity(value)

    @staticmethod
    def _tx_soft_key(tx: Transaction) -> str:
        """
        Soft identity for rows without external_id (and Revolut hard-id bridge).

        Includes fee, value_date, wall-clock completed/started from notes (when
        present), full descriptions, and counterparty so same-day same-amount
        exchanges with different times stay distinct.
        Intentionally omits account_id, file hash, and Balance so re-imports
        match after account remapping and Balance-hash external_id migration.
        """
        completed, started = wall_times_from_tx_notes(tx.notes)
        blob = "|".join(
            [
                str(tx.booking_date),
                str(tx.value_date or ""),
                completed,
                started,
                StatementService._norm_decimal(tx.amount),
                StatementService._norm_decimal(tx.fee_amount or 0),
                (tx.currency or "").upper(),
                (tx.merchant or "").strip().lower(),
                (tx.description or "").strip().lower(),
                (tx.original_description or "").strip().lower(),
                (tx.source_institution or "").strip().lower(),
                (tx.counterparty_account or "").strip().lower(),
                (tx.counterparty_name or "").strip().lower(),
            ]
        )
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
        return f"soft:{digest}"

    @staticmethod
    def _tx_keys(tx: Transaction) -> set[str]:
        """
        Identity key set for a transaction.

        Non-Revolut hard-id rows: hard only (Raiffeisen same-day same-amount
        distinct IDs must both survive).
        Revolut (or no external_id): soft∪hard so Balance-hash migration works
        without collapsing distinct same-day wall-clock times.
        """
        keys: set[str] = set()
        h = StatementService._tx_hard_key(tx)
        if h:
            keys.add(h)
        if not h or _is_revolut_source(tx.source_institution):
            keys.add(StatementService._tx_soft_key(tx))
        return keys

    @staticmethod
    def _event_hard_key(ev: InvestmentEvent) -> str | None:
        """Stable identity when parser emitted external_id."""
        if not ev.external_id:
            return None
        eid = ev.external_id.strip()
        # Already a full hard key (e.g. ext:Revolut:{digest})
        if eid.startswith("ext:"):
            return eid
        return f"ext:{ev.source}:{eid}"

    @staticmethod
    def _event_soft_key(ev: InvestmentEvent) -> str:
        """
        Soft identity for investment events across overlapping statement files.

        Fields: event_type, event_date, event_datetime (second-resolution UTC),
        ticker, qty/value/fees (normalized decimals), native_currency, source.

        Intentionally omits original_file_hash and source_file_id so tax-year
        re-exports of the same trades collapse against all-time imports.
        """
        blob = "|".join(
            [
                ev.event_type.value,
                str(ev.event_date),
                event_datetime_iso(ev.event_datetime),
                (ev.ticker or "").strip(),
                StatementService._norm_decimal(ev.quantity),
                StatementService._norm_decimal(ev.value_native),
                StatementService._norm_decimal(ev.fees_native or 0),
                (ev.native_currency or "").strip().upper(),
                (ev.source or "").strip(),
            ]
        )
        return "soft:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _event_keys(ev: InvestmentEvent) -> set[str]:
        """
        Identity keys for an investment event.

        Revolut (or missing external_id): soft∪hard so pre-external_id ledger
        rows still match new parser output and Sheets µs truncation.
        Non-Revolut with hard external_id: hard only (avoids soft over-collapse
        of distinct eToro ids that share coarse soft fields).
        """
        keys: set[str] = set()
        hard = StatementService._event_hard_key(ev)
        if hard:
            keys.add(hard)
        if not hard or _is_revolut_source(ev.source):
            keys.add(StatementService._event_soft_key(ev))
        return keys
