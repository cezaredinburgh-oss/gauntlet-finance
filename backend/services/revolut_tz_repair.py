"""
One-shot repair: Revolut event_datetime values that were stored by tagging
wall-clock times as UTC are re-read as Europe/Prague (or configured zone).

Idempotent via Settings key ``revolut_naive_tz_repaired_v1``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend.common.timeutil import (
    DEFAULT_STATEMENT_TIMEZONE,
    reinterpret_naive_utc_wall_as_zone,
    utc_now,
)
from backend.engines.statements import event_datetime_iso, revolut_event_external_id
from backend.schema.models import InvestmentEvent, Setting, SettingValueType

logger = logging.getLogger(__name__)

REPAIR_SETTING_KEY = "revolut_naive_tz_repaired_v1"


def _settings_map(repo) -> dict[str, Setting]:
    out: dict[str, Setting] = {}
    try:
        rows = repo.list_rows("Settings")
    except Exception:  # noqa: BLE001
        return out
    for r in rows:
        if isinstance(r, Setting) and r.key:
            out[r.key] = r
    return out


def already_repaired(repo) -> bool:
    m = _settings_map(repo)
    row = m.get(REPAIR_SETTING_KEY)
    if row is None:
        return False
    return str(row.value or "").strip().lower() in {"1", "true", "yes", "done"}


def _mark_repaired(repo, *, count: int) -> None:
    ts = utc_now()
    m = _settings_map(repo)
    existing = m.get(REPAIR_SETTING_KEY)
    row = Setting(
        id=existing.id if existing else uuid4(),
        key=REPAIR_SETTING_KEY,
        value="1",
        value_type=SettingValueType.STRING,
        description=f"Revolut naive→{DEFAULT_STATEMENT_TIMEZONE} UTC repair applied ({count} events)",
        created_at=existing.created_at if existing else ts,
        updated_at=ts,
    )
    try:
        repo.upsert_rows("Settings", [row])
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not persist %s: %s", REPAIR_SETTING_KEY, exc)


def repair_revolut_event_datetimes(
    repo,
    *,
    zone: str = DEFAULT_STATEMENT_TIMEZONE,
    force: bool = False,
) -> dict[str, Any]:
    """
    Rewrite Revolut InvestmentEvents event_datetime (and external_id) in place.

    Safe to call repeatedly: skips when Settings flag is set (unless force=True).
    """
    if not force and already_repaired(repo):
        return {"status": "skipped", "updated": 0, "reason": "already_repaired"}

    try:
        rows = repo.list_rows("InvestmentEvents")
    except Exception as exc:  # noqa: BLE001
        logger.warning("revolut tz repair: list events failed: %s", exc)
        return {"status": "error", "updated": 0, "reason": str(exc)}

    updated: list[InvestmentEvent] = []
    samples: list[dict[str, str | None]] = []
    for r in rows:
        if not isinstance(r, InvestmentEvent):
            continue
        if (r.source or "").strip().lower() != "revolut":
            continue
        if r.event_datetime is None:
            continue
        # Skip events already repaired
        if r.notes and "revolut_tz_repair_v1" in r.notes:
            continue
        old_dt = r.event_datetime
        if old_dt.tzinfo is None:
            old_dt = old_dt.replace(tzinfo=timezone.utc)
        new_dt = reinterpret_naive_utc_wall_as_zone(old_dt, zone=zone)
        if new_dt == old_dt.astimezone(timezone.utc):
            continue

        new_ext = r.external_id
        if r.external_id and str(r.external_id).startswith("ext:Revolut:"):
            new_ext = revolut_event_external_id(
                event_type=r.event_type.value if r.event_type else "",
                ticker=r.ticker,
                event_datetime=new_dt,
                quantity=r.quantity,
                value_native=r.value_native,
                fees_native=r.fees_native,
                currency=r.native_currency,
            )

        notes = r.notes or ""
        tag = "revolut_tz_repair_v1"
        if tag not in notes:
            notes = f"{notes}; {tag}".strip("; ")

        if len(samples) < 5:
            samples.append(
                {
                    "ticker": r.ticker,
                    "from": event_datetime_iso(old_dt),
                    "to": event_datetime_iso(new_dt),
                }
            )

        updated.append(
            r.model_copy(
                update={
                    "event_datetime": new_dt,
                    "event_date": new_dt.date(),
                    "external_id": new_ext,
                    "notes": notes,
                    "updated_at": utc_now(),
                }
            )
        )

    if updated:
        try:
            repo.upsert_rows("InvestmentEvents", updated)
        except Exception as exc:  # noqa: BLE001
            logger.warning("revolut tz repair: upsert failed: %s", exc)
            return {"status": "error", "updated": 0, "reason": str(exc)}

    _mark_repaired(repo, count=len(updated))
    logger.info(
        "revolut tz repair: updated %s events to zone %s", len(updated), zone
    )
    return {
        "status": "ok",
        "updated": len(updated),
        "zone": zone,
        "sample": samples,
    }


def ensure_revolut_tz_repaired(repo, *, zone: str | None = None) -> None:
    """Call from chart/import paths; no-op after first success."""
    try:
        from backend.config import get_settings

        z = zone or get_settings().statement_timezone
        repair_revolut_event_datetimes(repo, zone=z, force=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_revolut_tz_repaired failed: %s", exc)
