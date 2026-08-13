"""Disk-backed sheets repository: InMemory API + JSON snapshot on disk.

Used for the lab test account so data survives process restarts and logout
without Google Sheets.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.schema.models import SHEET_HEADERS, StatementFile, SheetRow, TAB_MODEL
from backend.sheets.repository import InMemorySheetsRepository

logger = logging.getLogger(__name__)


class DiskBackedSheetsRepository:
    """
    SheetsRepository-compatible store.

    Wraps InMemorySheetsRepository and persists all tabs to a single JSON file
    after every mutation (atomic replace via temp file + rename).
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._inner = InMemorySheetsRepository()
        self._lock = threading.RLock()
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
            payload = json.loads(raw) if raw.strip() else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("lab ledger load failed (%s): %s", self._path, exc)
            return
        if not isinstance(payload, dict):
            logger.warning("lab ledger root is not an object: %s", self._path)
            return
        tabs = payload.get("tabs")
        if not isinstance(tabs, dict):
            # Accept flat {tab: [rows]} for simplicity
            tabs = payload
        for tab, items in tabs.items():
            if tab not in TAB_MODEL or not isinstance(items, list):
                continue
            model_cls = TAB_MODEL[tab]
            rows: list[SheetRow] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    rows.append(model_cls.model_validate(item))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("skip bad lab row tab=%s: %s", tab, exc)
            try:
                self._inner.replace_all_rows(tab, rows)
            except Exception as exc:  # noqa: BLE001
                logger.warning("lab ledger tab load failed %s: %s", tab, exc)

    def _snapshot(self) -> dict[str, Any]:
        tabs: dict[str, list[dict[str, Any]]] = {}
        for tab in SHEET_HEADERS:
            rows = self._inner.list_rows(tab)
            tabs[tab] = [r.model_dump(mode="json") for r in rows]
        return {"version": 1, "tabs": tabs}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = self._snapshot()
        text = json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self._path)
        except OSError as exc:
            logger.exception("lab ledger save failed (%s): %s", self._path, exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def list_rows(self, tab: str) -> list[SheetRow]:
        with self._lock:
            return self._inner.list_rows(tab)

    def upsert_rows(self, tab: str, rows: list[SheetRow]) -> None:
        with self._lock:
            self._inner.upsert_rows(tab, rows)
            self._save()

    def get_by_id(self, tab: str, row_id: UUID) -> SheetRow | None:
        with self._lock:
            return self._inner.get_by_id(tab, row_id)

    def find_statement_by_hash(self, content_sha256: str) -> StatementFile | None:
        with self._lock:
            return self._inner.find_statement_by_hash(content_sha256)

    def delete_by_id(self, tab: str, row_id: UUID) -> bool:
        with self._lock:
            ok = self._inner.delete_by_id(tab, row_id)
            if ok:
                self._save()
            return ok

    def delete_by_ids(self, tab: str, row_ids: list[UUID]) -> int:
        with self._lock:
            n = self._inner.delete_by_ids(tab, row_ids)
            if n:
                self._save()
            return n

    def replace_all_rows(self, tab: str, rows: list[SheetRow]) -> None:
        with self._lock:
            self._inner.replace_all_rows(tab, rows)
            self._save()

    def clear_all_for_tests(self) -> None:
        """Wipe in-memory + disk (tests only)."""
        with self._lock:
            self._inner = InMemorySheetsRepository()
            if self._path.is_file():
                try:
                    self._path.unlink()
                except OSError:
                    pass
            self._save()
