"""Repository protocol and in-memory implementation for domain services."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from backend.schema.models import SHEET_HEADERS, StatementFile, SheetRow, TAB_MODEL


class SheetsRepository(Protocol):
    """Persistence boundary used by domain services (inject in FastAPI later)."""

    def list_rows(self, tab: str) -> list[SheetRow]: ...

    def upsert_rows(self, tab: str, rows: list[SheetRow]) -> None: ...

    def get_by_id(self, tab: str, row_id: UUID) -> SheetRow | None: ...

    def find_statement_by_hash(self, content_sha256: str) -> StatementFile | None: ...

    def delete_by_id(self, tab: str, row_id: UUID) -> bool: ...

    def delete_by_ids(self, tab: str, row_ids: list[UUID]) -> int:
        """Delete many rows; returns how many were removed. Default: loop delete_by_id."""
        ...

    def replace_all_rows(self, tab: str, rows: list[SheetRow]) -> None: ...


class InMemorySheetsRepository:
    """Dict-backed repository for tests and local pipelines."""

    def __init__(self) -> None:
        self._data: dict[str, dict[UUID, SheetRow]] = {
            tab: {} for tab in SHEET_HEADERS
        }

    def list_rows(self, tab: str) -> list[SheetRow]:
        return list(self._data[tab].values())

    def upsert_rows(self, tab: str, rows: list[SheetRow]) -> None:
        bucket = self._data[tab]
        expected = TAB_MODEL[tab]
        for row in rows:
            if not isinstance(row, expected):
                raise TypeError(
                    f"expected {expected.__name__} for tab {tab}, got {type(row).__name__}"
                )
            bucket[row.id] = row

    def get_by_id(self, tab: str, row_id: UUID) -> SheetRow | None:
        return self._data[tab].get(row_id)

    def find_statement_by_hash(self, content_sha256: str) -> StatementFile | None:
        needle = content_sha256.lower()
        for row in self._data["StatementFiles"].values():
            assert isinstance(row, StatementFile)
            if row.archived:
                continue
            if row.content_sha256.lower() == needle:
                return row
        return None

    def delete_by_id(self, tab: str, row_id: UUID) -> bool:
        return self._data[tab].pop(row_id, None) is not None

    def delete_by_ids(self, tab: str, row_ids: list[UUID]) -> int:
        n = 0
        for rid in row_ids:
            if self.delete_by_id(tab, rid):
                n += 1
        return n

    def replace_all_rows(self, tab: str, rows: list[SheetRow]) -> None:
        expected = TAB_MODEL[tab]
        bucket: dict[UUID, SheetRow] = {}
        for row in rows:
            if not isinstance(row, expected):
                raise TypeError(
                    f"expected {expected.__name__} for tab {tab}, got {type(row).__name__}"
                )
            bucket[row.id] = row
        self._data[tab] = bucket
