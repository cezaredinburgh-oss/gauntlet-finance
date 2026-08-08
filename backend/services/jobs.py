"""In-process background job registry (single-user ops).

Not multi-worker durable queues — suitable for Railway single replica.
Single-flight per job kind to avoid double FX/Sheets writes.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from backend.schema.models import Transaction
from backend.services.maintenance import backfill_amount_usd, fetch_cnb_range
from backend.sheets.repository import SheetsRepository

logger = logging.getLogger(__name__)

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_KIND_LOCKS: dict[str, threading.Lock] = {}
_KIND_LOCKS_GUARD = threading.Lock()

JobFn = Callable[[SheetsRepository, dict[str, Any]], dict[str, Any]]


def _kind_lock(kind: str) -> threading.Lock:
    with _KIND_LOCKS_GUARD:
        if kind not in _KIND_LOCKS:
            _KIND_LOCKS[kind] = threading.Lock()
        return _KIND_LOCKS[kind]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_jobs(*, limit: int = 20) -> list[dict[str, Any]]:
    with _JOBS_LOCK:
        items = sorted(
            _JOBS.values(),
            key=lambda j: j.get("started_at") or "",
            reverse=True,
        )
    return items[: max(1, min(limit, 100))]


def get_job(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def _set_job(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        row = _JOBS.get(job_id)
        if not row:
            return
        row.update(fields)


def start_job(
    kind: str,
    repo: SheetsRepository,
    *,
    params: dict[str, Any] | None = None,
    runner: JobFn,
) -> dict[str, Any]:
    """Start a background job; returns job stub. Fails if same kind already running."""
    params = params or {}
    lock = _kind_lock(kind)
    if not lock.acquire(blocking=False):
        return {
            "status": "rejected",
            "error": f"job kind '{kind}' already running",
            "kind": kind,
        }

    job_id = str(uuid.uuid4())
    stub = {
        "id": job_id,
        "kind": kind,
        "status": "running",
        "started_at": _now_iso(),
        "finished_at": None,
        "params": params,
        "result": None,
        "error": None,
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = stub

    def _run() -> None:
        try:
            result = runner(repo, params)
            _set_job(
                job_id,
                status="done",
                result=result,
                finished_at=_now_iso(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("job %s (%s) failed", job_id, kind)
            _set_job(
                job_id,
                status="error",
                error=str(exc),
                finished_at=_now_iso(),
            )
        finally:
            lock.release()

    threading.Thread(target=_run, daemon=True, name=f"job-{kind}").start()
    return {"job_id": job_id, "status": "running", "kind": kind}


def _ledger_date_span(repo: SheetsRepository) -> tuple[date, date]:
    today = date.today()
    txs = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    if not txs:
        return today - timedelta(days=30), today
    dates = [t.booking_date for t in txs if t.booking_date and not t.archived]
    if not dates:
        return today - timedelta(days=30), today
    return min(dates), max(max(dates), today)


def run_fx_fetch_cnb(repo: SheetsRepository, params: dict[str, Any]) -> dict[str, Any]:
    """Fetch CNB rates in ≤400-day chunks for ledger span or explicit range."""
    if params.get("date_from") and params.get("date_to"):
        d0 = date.fromisoformat(str(params["date_from"]))
        d1 = date.fromisoformat(str(params["date_to"]))
    else:
        d0, d1 = _ledger_date_span(repo)

    if d1 < d0:
        d0, d1 = d1, d0

    chunks: list[dict[str, Any]] = []
    errors: list[str] = []
    rates_total = 0
    cur = d0
    while cur <= d1:
        end = min(cur + timedelta(days=399), d1)
        part = fetch_cnb_range(repo, date_from=cur, date_to=end)
        chunks.append(
            {
                "date_from": part.get("date_from"),
                "date_to": part.get("date_to"),
                "rates_upserted": part.get("rates_upserted"),
                "error_count": part.get("error_count"),
            }
        )
        rates_total += int(part.get("rates_upserted") or 0)
        errors.extend(part.get("errors") or [])
        cur = end + timedelta(days=1)

    return {
        "date_from": d0.isoformat(),
        "date_to": d1.isoformat(),
        "chunks": len(chunks),
        "rates_upserted": rates_total,
        "error_count": len(errors),
        "errors": errors[:20],
        "chunk_detail": chunks,
    }


def run_fx_backfill_amounts(
    repo: SheetsRepository, params: dict[str, Any]
) -> dict[str, Any]:
    limit = int(params.get("limit") or 5000)
    max_passes = int(params.get("max_passes") or 5)
    fetch_missing = bool(params.get("fetch_missing_rates", True))
    passes: list[dict[str, Any]] = []
    for i in range(max_passes):
        result = backfill_amount_usd(
            repo, limit=limit, fetch_missing_rates=fetch_missing
        )
        passes.append({"pass": i + 1, **result})
        filled = int(result.get("filled_usd_approx") or 0) + int(
            result.get("filled_czk_approx") or 0
        )
        if filled == 0 and int(result.get("priority_attempted") or 0) == 0:
            break
        if int(result.get("missing_usd_after") or 0) == 0 and int(
            result.get("missing_czk_after") or 0
        ) == 0:
            break
    last = passes[-1] if passes else {}
    return {
        "passes": len(passes),
        "last": last,
        "history": passes,
    }


def run_fx_full_pipeline(
    repo: SheetsRepository, params: dict[str, Any]
) -> dict[str, Any]:
    """Fetch CNB for ledger span, then backfill amount legs."""
    fetch_result = run_fx_fetch_cnb(repo, params)
    backfill_result = run_fx_backfill_amounts(repo, params)
    return {"fetch": fetch_result, "backfill": backfill_result}


def run_portfolio_snapshot_job(
    repo: SheetsRepository, params: dict[str, Any]
) -> dict[str, Any]:
    from backend.services.portfolio_history import run_portfolio_snapshot_job as _run

    return _run(repo, params)


KIND_RUNNERS: dict[str, JobFn] = {
    "fx-fetch-cnb": run_fx_fetch_cnb,
    "fx-backfill-amounts": run_fx_backfill_amounts,
    "fx-full": run_fx_full_pipeline,
    "portfolio-snapshot": run_portfolio_snapshot_job,
}


def start_known_job(
    kind: str, repo: SheetsRepository, *, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    runner = KIND_RUNNERS.get(kind)
    if runner is None:
        return {
            "status": "rejected",
            "error": f"unknown job kind '{kind}'",
            "known": sorted(KIND_RUNNERS),
        }
    return start_job(kind, repo, params=params or {}, runner=runner)
