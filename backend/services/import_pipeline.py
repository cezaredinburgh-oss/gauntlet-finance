"""
End-to-end statement import: parse → dedupe → categorize → match transfers →
lots FIFO → persist via repository.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from backend.common.timeutil import utc_now
from backend.engines.categorize import CategoryEngine
from backend.engines.lots import FifoResult, LotEngine
from backend.engines.statements import StatementService
from backend.engines.transfer_match import match_internal_transfers
from backend.parsers import parse_statement_bytes
from backend.schema.models import (
    Account,
    Category,
    CategoryRule,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    StatementFile,
    StatementFileStatus,
    Transaction,
)
from backend.services.fx_amounts import build_fx_service, enrich_transaction_amounts
from backend.services.lot_costs import enrich_lots, ensure_fx_coverage
from backend.services.lot_rebuild import (
    collect_tickers,
    rebuild_lots_for_tickers,
    should_rebuild_tickers,
)
from backend.sheets.repository import SheetsRepository

# Process-level serialize: concurrent uploads wait (do not reject).
# Multi-tenant: one lock per tenant id so tenants do not block each other.
_IMPORT_LOCK = threading.Lock()
_TENANT_IMPORT_LOCKS: dict[str, threading.Lock] = {}
_TENANT_LOCKS_GUARD = threading.Lock()


def _import_lock() -> threading.Lock:
    try:
        from backend.tenancy.context import get_tenant_id

        tid = get_tenant_id()
    except Exception:  # noqa: BLE001
        tid = None
    if not tid:
        return _IMPORT_LOCK
    with _TENANT_LOCKS_GUARD:
        lock = _TENANT_IMPORT_LOCKS.get(tid)
        if lock is None:
            lock = threading.Lock()
            _TENANT_IMPORT_LOCKS[tid] = lock
        return lock


@dataclass
class UploadSummary:
    status: str
    content_sha256: str
    parser_key: str | None = None
    institution: str | None = None
    statement_file_id: str | None = None
    rows_parsed: int = 0
    transactions_written: int = 0
    events_written: int = 0
    lots_written: int = 0
    transfer_pairs_linked: int = 0
    transactions_deduped: int = 0
    events_deduped: int = 0
    message: str = ""
    errors: list[str] = field(default_factory=list)


def _filename_parser_hint(filename: str, parser_key: str | None) -> str | None:
    """
    Optional note when the filename clearly suggests a different product than
    the selected parser (secondary UX; detection still wins).
    """
    if not parser_key or not filename:
        return None
    name = filename.lower()
    hints: list[tuple[tuple[str, ...], str]] = [
        (("crypto", "digital asset"), "revolut_crypto"),
        (("stock", "securit", "trading"), "revolut_stocks"),
        (("checking", "expense", "daily"), "revolut_expenses"),
        (("etoro",), "etoro_account_statement"),
        (("raiffeisen", "rb "), "raiffeisen_cz"),
    ]
    for needles, expected in hints:
        if any(n in name for n in needles) and parser_key != expected:
            # Avoid false positives like "crypto" inside unrelated names when
            # parser is already a Revolut family member and name is mixed.
            if expected.startswith("revolut_") and parser_key.startswith("revolut_"):
                return (
                    f"Note: filename suggests {expected} but detected {parser_key}"
                )
            if not expected.startswith("revolut_"):
                return (
                    f"Note: filename suggests {expected} but detected {parser_key}"
                )
    return None


def _build_import_message(
    *,
    parser_key: str | None,
    filename: str,
    rows_parsed: int,
    transactions_written: int,
    events_written: int,
    transactions_deduped: int,
    events_deduped: int,
) -> str:
    """Human summary: N parsed · X already in ledger · Y new."""
    parts: list[str] = []
    if transactions_written or transactions_deduped:
        tx_parsed = transactions_written + transactions_deduped
        parts.append(
            f"{tx_parsed} parsed · {transactions_deduped} already in ledger · "
            f"{transactions_written} new"
        )
    if events_written or events_deduped:
        ev_parsed = events_written + events_deduped
        label = "events"
        parts.append(
            f"{ev_parsed} {label} · {events_deduped} already in ledger · "
            f"{events_written} new"
        )
    if not parts:
        parts.append(f"{rows_parsed} rows parsed · nothing new")
    msg = " · ".join(parts) if len(parts) == 1 else "; ".join(parts)
    if parser_key:
        msg = f"[{parser_key}] {msg}"
    hint = _filename_parser_hint(filename, parser_key)
    if hint:
        msg = f"{msg}. {hint}"
    return msg


def _account_map(accounts: list[Account]) -> dict[str, UUID]:
    """currency → account id, plus default."""
    m: dict[str, UUID] = {}
    for a in accounts:
        if a.archived or not a.is_active:
            continue
        m[a.currency.upper()] = a.id
        # Prefer checking accounts as default
        if "default" not in m or a.account_type.value == "Checking":
            m["default"] = a.id
    if "default" not in m and accounts:
        m["default"] = accounts[0].id
    return m


class ImportPipeline:
    def __init__(
        self,
        repo: SheetsRepository,
        *,
        exemption_days: int = 1095,
    ) -> None:
        self.repo = repo
        self.statements = StatementService(repo)
        self.exemption_days = exemption_days
        # FX attached per upload so CNB rates in the sheet convert CZK lots
        self.lot_engine = LotEngine(exemption_days=exemption_days)

    def upload(
        self,
        *,
        filename: str,
        content: bytes,
        account_ids: dict[str, UUID] | None = None,
        now: datetime | None = None,
    ) -> UploadSummary:
        # Serialize concurrent imports process-wide (wait, do not reject).
        with _import_lock():
            return self._upload_unlocked(
                filename=filename,
                content=content,
                account_ids=account_ids,
                now=now,
            )

    def _upload_unlocked(
        self,
        *,
        filename: str,
        content: bytes,
        account_ids: dict[str, UUID] | None = None,
        now: datetime | None = None,
    ) -> UploadSummary:
        ts = now or utc_now()
        h = self.statements.content_hash(content)

        # Keep bytes for ERROR/PENDING retry without re-selecting the file
        try:
            from backend.services.upload_store import store_upload

            store_upload(h, content)
        except Exception:  # noqa: BLE001
            pass

        if self.statements.is_duplicate(h):
            existing = self.statements.find_by_hash(h)
            return UploadSummary(
                status="already_imported",
                content_sha256=h,
                statement_file_id=str(existing.id) if existing else None,
                message="File already imported (same SHA-256)",
            )

        accounts = [
            a
            for a in self.repo.list_rows("Accounts")
            if isinstance(a, Account)
        ]
        if not accounts:
            # Persist seed accounts so later uploads share stable account_ids.
            # Always use public-safe accounts (synthetic masks) — never personal.
            try:
                from backend.scripts.seed_dev_repo import seed_minimal

                seed_minimal(self.repo, public_demo=True)
                accounts = [
                    a
                    for a in self.repo.list_rows("Accounts")
                    if isinstance(a, Account)
                ]
            except Exception:  # noqa: BLE001
                pass

        acc_map = account_ids or _account_map(accounts)
        if not acc_map:
            # Last resort: create and store a default checking account
            from backend.schema.models import AccountType, Institution
            from backend.common.timeutil import utc_now as _now

            ts0 = _now()
            default_id = uuid4()
            bootstrap = Account(
                id=default_id,
                name="Default",
                institution=Institution.OTHER,
                account_type=AccountType.CHECKING,
                currency="USD",
                is_active=True,
                created_at=ts0,
                updated_at=ts0,
            )
            self.repo.upsert_rows("Accounts", [bootstrap])
            acc_map = {"default": default_id, "USD": default_id, "CZK": default_id}

        # Broad currency fallbacks to default
        for ccy in (
            "CZK", "USD", "EUR", "GBP", "INR", "PLN", "CHF", "RON", "HUF",
            "SEK", "DKK", "NOK", "AUD", "CAD", "JPY", "SGD", "HKD",
        ):
            acc_map.setdefault(ccy, acc_map["default"])

        reg = self.statements.register_statement(
            filename=filename,
            file_bytes=content,
            institution="Unknown",
            row_count=0,
            parser_key=None,
            status=StatementFileStatus.PENDING,
            now=ts,
        )
        if reg.status == "duplicate":
            return UploadSummary(
                status="already_imported",
                content_sha256=h,
                statement_file_id=str(reg.statement.id),
                message="File already imported",
            )

        # Everything after register is best-effort: on any failure mark ERROR so
        # the same file can be re-uploaded (row dedupe recovers partial writes).
        try:
            return self._import_registered(
                reg_statement=reg.statement,
                content=content,
                filename=filename,
                acc_map=acc_map,
                content_sha256=h,
                ts=ts,
            )
        except Exception as exc:  # noqa: BLE001
            try:
                self.statements.mark_status(
                    reg.statement.id,
                    StatementFileStatus.ERROR,
                    notes=str(exc)[:1500],
                    now=utc_now(),
                )
            except Exception:  # noqa: BLE001
                # Do not hide the original import failure if ERROR write fails.
                pass
            return UploadSummary(
                status="error",
                content_sha256=h,
                statement_file_id=str(reg.statement.id),
                message=(
                    f"{exc}. File marked as failed — you can re-upload the same "
                    "file to resume (already-written rows are skipped)."
                ),
                errors=[str(exc)],
            )

    def _import_registered(
        self,
        *,
        reg_statement: StatementFile,
        content: bytes,
        filename: str,
        acc_map: dict[str, UUID],
        content_sha256: str,
        ts: datetime,
    ) -> UploadSummary:
        """Parse + persist for a StatementFiles row already registered as PENDING."""
        parsed = parse_statement_bytes(
            content,
            account_ids=acc_map,
            existing_hashes=set(),  # already gated
            filename=filename,
            source_file_id=reg_statement.id,
            now=ts,
        )

        # Update statement metadata (still PENDING until writes finish)
        self.repo.upsert_rows(
            "StatementFiles",
            [
                reg_statement.model_copy(
                    update={
                        "institution": parsed.institution or "Unknown",
                        "parser_key": parsed.parser_key,
                        "row_count": parsed.row_count,
                        "updated_at": ts,
                    }
                )
            ],
        )

        # Dedupe against existing (covers retries after partial write)
        existing_tx = [
            r for r in self.repo.list_rows("Transactions") if isinstance(r, Transaction)
        ]
        existing_ev = [
            r
            for r in self.repo.list_rows("InvestmentEvents")
            if isinstance(r, InvestmentEvent)
        ]
        # One-shot migrate legacy Revolut naive-UTC clocks before dedupe
        try:
            from backend.services.revolut_tz_repair import ensure_revolut_tz_repaired

            ensure_revolut_tz_repaired(self.repo)
            existing_ev = [
                r
                for r in self.repo.list_rows("InvestmentEvents")
                if isinstance(r, InvestmentEvent)
            ]
        except Exception:  # noqa: BLE001
            pass

        d_tx = StatementService.dedupe_transactions(existing_tx, parsed.transactions)
        d_ev = StatementService.dedupe_events(existing_ev, parsed.investment_events)

        # Ensure Digital Assets Europe crypto-pot rule before categorize
        try:
            from backend.schema.ensure_defaults import ensure_digital_assets_rule

            ensure_digital_assets_rule(self.repo)
        except Exception:  # noqa: BLE001
            pass

        # Categorize new transactions
        categories = [
            r for r in self.repo.list_rows("Categories") if isinstance(r, Category)
        ]
        rules = [
            r for r in self.repo.list_rows("CategoryRules") if isinstance(r, CategoryRule)
        ]
        cat_engine = CategoryEngine(rules=rules, categories=categories)
        cat_result = cat_engine.categorize_many(d_tx.transactions)

        # Internal transfer match on union of existing + new
        combined = existing_tx + cat_result.transactions
        match_result = match_internal_transfers(combined)
        matched_by_id = {t.id: t for t in match_result.transactions}
        new_tx_final = [matched_by_id[t.id] for t in cat_result.transactions]
        existing_updates = []
        for t in existing_tx:
            m = matched_by_id.get(t.id)
            if m and (
                m.is_internal_transfer != t.is_internal_transfer
                or m.transfer_group_id != t.transfer_group_id
            ):
                existing_updates.append(m)

        # Lots: ticker-scoped rebuild when ledger already has events/lots for
        # the same tickers (ERROR retry / incremental), else incremental FIFO.
        fx = build_fx_service(self.repo)
        self.lot_engine = LotEngine(exemption_days=self.exemption_days, fx=fx)
        existing_lots = [
            r for r in self.repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)
        ]
        new_non_alloc = [
            e
            for e in d_ev.investment_events
            if e.event_type != InvestmentEventType.LOT_ALLOCATION
        ]
        parsed_non_alloc = [
            e
            for e in parsed.investment_events
            if e.event_type != InvestmentEventType.LOT_ALLOCATION
        ]

        # Tickers from new events; on full dedupe retry use parse tickers so we
        # still rebuild lots that were never written.
        touched = collect_tickers(new_non_alloc)
        force_rebuild = False
        if not touched and parsed_non_alloc:
            touched = collect_tickers(parsed_non_alloc)
            force_rebuild = True

        fifo: FifoResult
        stale_alloc_ids: list[UUID] = []
        stale_lot_ids: list[UUID] = []

        if touched and (
            force_rebuild
            or should_rebuild_tickers(
                touched_tickers=touched,
                existing_lots=existing_lots,
                existing_events=existing_ev,
            )
        ):
            plan = rebuild_lots_for_tickers(
                existing_lots=existing_lots,
                existing_events=existing_ev,
                new_events=new_non_alloc,
                touched_tickers=touched,
                engine=self.lot_engine,
                now=ts,
            )
            fifo = FifoResult(
                lots=plan.lots,
                events=plan.events,
                allocations_created=plan.allocations_created,
            )
            stale_alloc_ids = plan.stale_allocation_ids
            stale_lot_ids = plan.stale_lot_ids
        elif new_non_alloc:
            fifo = self.lot_engine.apply_events(
                existing_lots, new_non_alloc, now=ts
            )
        else:
            fifo = FifoResult(lots=list(existing_lots), events=[], allocations_created=0)

        enriched_lots = enrich_lots(
            fifo.lots,
            fx,
            repo=self.repo,
            persist=False,
            fetch_missing_rates=True,
        )

        # Cash: historical amount_usd / amount_czk on booking_date (no GET-side flush)
        if new_tx_final:
            ensure_fx_coverage(
                fx,
                (t.booking_date for t in new_tx_final),
                repo=self.repo,
                fetch=True,
            )
            filled: list[Transaction] = []
            for t in new_tx_final:
                enriched_tx, _ = enrich_transaction_amounts(t, fx)
                filled.append(enriched_tx)
            new_tx_final = filled

        # Persist — only mark Imported after all of these succeed
        if new_tx_final:
            self.repo.upsert_rows("Transactions", new_tx_final)
        if existing_updates:
            self.repo.upsert_rows("Transactions", existing_updates)

        # Drop stale lots/allocs for rebuilt tickers before writing fresh rows
        for alloc_id in stale_alloc_ids:
            self.repo.delete_by_id("InvestmentEvents", alloc_id)
        for lot_id in stale_lot_ids:
            self.repo.delete_by_id("InvestmentLots", lot_id)

        if fifo.events:
            self.repo.upsert_rows("InvestmentEvents", fifo.events)
        if enriched_lots:
            # On ticker rebuild, write full lot set for those tickers (plus others
            # already in fifo.lots). On incremental path, upsert changed lots.
            self.repo.upsert_rows("InvestmentLots", enriched_lots)
            fifo = FifoResult(
                lots=enriched_lots,
                events=fifo.events,
                allocations_created=fifo.allocations_created,
            )

        self.statements.mark_imported(
            reg_statement.id,
            row_count=parsed.row_count,
            now=ts,
        )

        tx_written = len(new_tx_final)
        ev_written = len(d_ev.investment_events)
        msg = _build_import_message(
            parser_key=parsed.parser_key,
            filename=filename,
            rows_parsed=parsed.row_count,
            transactions_written=tx_written,
            events_written=ev_written,
            transactions_deduped=d_tx.dropped_transactions,
            events_deduped=d_ev.dropped_events,
        )
        # Count lots for touched tickers when we rebuilt; else all fifo lots written
        if touched and (force_rebuild or stale_lot_ids or stale_alloc_ids or fifo.events):
            lots_written = sum(
                1
                for lot in fifo.lots
                if (lot.ticker or "").strip().upper() in touched
            )
        else:
            lots_written = len(fifo.lots) if new_non_alloc else 0

        return UploadSummary(
            status="imported",
            content_sha256=content_sha256,
            parser_key=parsed.parser_key,
            institution=parsed.institution,
            statement_file_id=str(reg_statement.id),
            rows_parsed=parsed.row_count,
            transactions_written=tx_written,
            events_written=ev_written,
            lots_written=lots_written,
            transfer_pairs_linked=match_result.pairs_linked,
            transactions_deduped=d_tx.dropped_transactions,
            events_deduped=d_ev.dropped_events,
            message=msg,
        )
