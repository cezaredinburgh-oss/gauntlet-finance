"""
Google Sheets repository using google-api-python-client.

Read whole tabs into an in-memory cache (with row-index map). Writes use
**row-level patches** via ``values.batchUpdate`` so categorization does not
rewrite 10k+ rows. Full clear+rewrite remains available for ``replace_all_rows``.
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.schema.models import SHEET_HEADERS, StatementFile, SheetRow, TAB_MODEL
from backend.sheets.codec import model_to_row, models_to_grid, row_to_model

logger = logging.getLogger(__name__)


def _http_status(exc: HttpError) -> int | None:
    resp = getattr(exc, "resp", None)
    if resp is None:
        return None
    try:
        return int(resp.status)
    except (TypeError, ValueError):
        return None


def _is_retryable_sheets_error(exc: HttpError) -> bool:
    """429 rate limits and transient 5xx / 408."""
    status = _http_status(exc)
    if status in (408, 429, 500, 502, 503, 504):
        return True
    # Some client libs only put the code in the message body
    msg = str(exc).lower()
    return "rate_limit" in msg or "quota exceeded" in msg or "ratelimit" in msg


def execute_sheets_request(
    request: Any,
    *,
    what: str,
    max_attempts: int = 10,
    base_delay_s: float = 2.0,
    max_delay_s: float = 75.0,
) -> Any:
    """
    Execute a googleapiclient request with exponential backoff on 429/5xx
    and transient network timeouts (SSL read TimeoutError / socket errors).

    Google Sheets free-tier write quota is ~60 writes/min/user; large statement
    imports can hit that mid-append. Retrying with backoff is safer than
    marking the whole file imported-or-lost.

    Unhandled socket timeouts used to bubble as ASGI 500s and leave uvicorn
    blocked long enough for Railway's edge to return 502 (~250s).
    """
    delay = base_delay_s
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return request.execute()
        except HttpError as exc:
            last_exc = exc
            if not _is_retryable_sheets_error(exc) or attempt >= max_attempts:
                raise
            # Honour Retry-After when Google sends it
            retry_after = None
            resp = getattr(exc, "resp", None)
            if resp is not None:
                try:
                    raw = resp.get("retry-after") if hasattr(resp, "get") else None
                    if raw is not None:
                        retry_after = float(raw)
                except (TypeError, ValueError):
                    retry_after = None
            sleep_for = retry_after if retry_after is not None else delay
            # Jitter so concurrent writers do not stampede
            sleep_for = min(max_delay_s, sleep_for + random.uniform(0, 0.5))
            logger.warning(
                "Sheets %s hit %s (attempt %s/%s); sleeping %.1fs then retry",
                what,
                _http_status(exc) or exc,
                attempt,
                max_attempts,
                sleep_for,
            )
            time.sleep(sleep_for)
            delay = min(max_delay_s, delay * 2)
        except (TimeoutError, OSError, ConnectionError) as exc:
            # SSL read timeouts show as TimeoutError from ssl.py; treat as retryable.
            last_exc = exc
            if attempt >= max_attempts:
                raise
            sleep_for = min(max_delay_s, delay + random.uniform(0, 0.5))
            logger.warning(
                "Sheets %s network timeout/error %s (attempt %s/%s); "
                "sleeping %.1fs then retry",
                what,
                type(exc).__name__,
                attempt,
                max_attempts,
                sleep_for,
            )
            time.sleep(sleep_for)
            delay = min(max_delay_s, delay * 2)
    assert last_exc is not None
    raise last_exc

# spreadsheets + drive.file: open shared sheets and create SA-owned spreadsheets
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# Common default locations (relative to process cwd / project root)
DEFAULT_SA_PATHS = (
    "secrets/service-account.json",
    "secrets/credentials.json",
    "service-account.json",
    "credentials.json",
)


def resolve_service_account_path(explicit: str | None = None) -> Path | None:
    """Return first existing service-account JSON path."""
    candidates: list[str] = []
    if explicit and str(explicit).strip():
        candidates.append(str(explicit).strip())
    candidates.extend(DEFAULT_SA_PATHS)
    for c in candidates:
        p = Path(c)
        if not p.is_absolute():
            # try cwd, then parent of backend/
            if p.is_file():
                return p.resolve()
            alt = Path(__file__).resolve().parents[2] / c
            if alt.is_file():
                return alt.resolve()
        elif p.is_file():
            return p
    return None


def load_service_account_info(
    *,
    json_path: str | None = None,
    json_inline: str | None = None,
) -> dict[str, Any]:
    if json_inline and json_inline.strip():
        return json.loads(json_inline)
    path = resolve_service_account_path(json_path)
    if path is None:
        raise ValueError(
            "service account JSON not found. Set GOOGLE_APPLICATION_CREDENTIALS "
            "or place the key at secrets/service-account.json"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def service_account_email(
    *,
    json_path: str | None = None,
    json_inline: str | None = None,
) -> str:
    info = load_service_account_info(json_path=json_path, json_inline=json_inline)
    email = info.get("client_email")
    if not email:
        raise ValueError("service account JSON missing client_email")
    return str(email)


def credentials_from_service_account(
    *,
    json_path: str | None = None,
    json_inline: str | None = None,
) -> service_account.Credentials:
    if json_inline and json_inline.strip():
        info = json.loads(json_inline)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    path = resolve_service_account_path(json_path)
    if path is not None:
        return service_account.Credentials.from_service_account_file(
            str(path), scopes=SCOPES
        )
    raise ValueError(
        "service account credentials not configured "
        "(set GOOGLE_APPLICATION_CREDENTIALS or secrets/service-account.json)"
    )


def credentials_from_user_token(
    *,
    token: str,
    refresh_token: str | None,
    client_id: str,
    client_secret: str,
    token_uri: str = "https://oauth2.googleapis.com/token",
) -> UserCredentials:
    return UserCredentials(
        token=token,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )


def create_spreadsheet(
    credentials: service_account.Credentials | UserCredentials,
    *,
    title: str = "Gauntlet Finance Data",
    share_with_email: str | None = None,
) -> dict[str, str]:
    """
    Create a new Google Spreadsheet owned by the service account.

    Optionally share with a human Google account as writer so they can open it
    in the browser. Returns spreadsheet_id and url.
    """
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    created = (
        sheets.spreadsheets()
        .create(body={"properties": {"title": title}})
        .execute()
    )
    sid = str(created["spreadsheetId"])
    url = str(
        created.get("spreadsheetUrl")
        or f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    )

    if share_with_email and share_with_email.strip():
        email = share_with_email.strip()
        try:
            drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
            drive.permissions().create(
                fileId=sid,
                body={
                    "type": "user",
                    "role": "writer",
                    "emailAddress": email,
                },
                sendNotificationEmail=False,
                fields="id",
            ).execute()
        except HttpError as exc:
            logger.warning("Could not share spreadsheet with %s: %s", email, exc)
            return {
                "spreadsheet_id": sid,
                "url": url,
                "shared_with": "",
                "share_warning": str(exc),
            }
        return {"spreadsheet_id": sid, "url": url, "shared_with": email}

    return {"spreadsheet_id": sid, "url": url, "shared_with": ""}


class GoogleSheetsRepository:
    """
    Sheets-backed :class:`SheetsRepository`.

    Caches tab contents after first read. ``upsert_rows`` merges by id and
    **patches only changed rows** via ``values.batchUpdate`` (fast for
    categorization). Full clear+rewrite is reserved for ``replace_all_rows``
    and rare compacting paths.
    """

    # Larger chunks = fewer write requests (quota is ~60 writes/min/user).
    # 800 rows × ~40 cols stays well under the cells-per-request limit.
    _PATCH_CHUNK = 800
    # Prefer a long TTL: this process is the writer; invalidate/refresh on write.
    # External scripts can still force a re-read after TTL or process restart.
    _DEFAULT_TAB_TTL_SECONDS = 600.0

    def __init__(
        self,
        spreadsheet_id: str,
        credentials: Any,
        *,
        ensure_tabs: bool = True,
        tab_cache_ttl_seconds: float | None = None,
    ) -> None:
        if not spreadsheet_id:
            raise ValueError("spreadsheet_id is required")
        self.spreadsheet_id = spreadsheet_id
        self._creds = credentials
        self._service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self._cache: dict[str, dict[UUID, SheetRow]] = {}
        self._cache_loaded_at: dict[str, float] = {}
        # id -> 1-based sheet row (header is row 1; data starts at 2)
        self._row_index: dict[str, dict[UUID, int]] = {}
        # next free 1-based row for appends
        self._next_row: dict[str, int] = {}
        self._dirty: set[str] = set()
        self._tab_cache_ttl_seconds = (
            float(tab_cache_ttl_seconds)
            if tab_cache_ttl_seconds is not None
            else self._DEFAULT_TAB_TTL_SECONDS
        )
        # Serialize concurrent first-loads of the same tab (dashboard + alerts race)
        from threading import Lock

        self._load_lock = Lock()
        self._tab_locks: dict[str, Lock] = {}
        self._tab_locks_guard = Lock()
        if ensure_tabs:
            self.ensure_all_tabs()

    # ------------------------------------------------------------------
    # Tab setup
    # ------------------------------------------------------------------

    def list_tab_names(self) -> list[str]:
        meta = (
            self._service.spreadsheets()
            .get(spreadsheetId=self.spreadsheet_id)
            .execute()
        )
        return [s["properties"]["title"] for s in meta.get("sheets", [])]

    def ensure_tab(self, tab: str) -> str:
        """Create a single missing tab + header row. Idempotent."""
        if tab not in SHEET_HEADERS:
            raise KeyError(f"unknown tab {tab}")
        existing = set(self.list_tab_names())
        if tab not in existing:
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": tab,
                                    "gridProperties": {
                                        "rowCount": 10000,
                                        "columnCount": max(
                                            26, len(SHEET_HEADERS[tab]) + 4
                                        ),
                                    },
                                }
                            }
                        }
                    ]
                },
            ).execute()
            action = "created"
        else:
            action = "exists"
        hdr = self._ensure_header_row(tab, SHEET_HEADERS[tab])
        if action == "exists":
            return hdr
        if hdr != "headers_ok":
            return f"{action}+{hdr}"
        return action

    def ensure_all_tabs(self) -> dict[str, str]:
        """
        Create missing tabs and ensure header rows match SHEET_HEADERS.

        Idempotent: safe to run many times. Does not wipe data rows when
        headers already match. Returns per-tab status messages.
        """
        status: dict[str, str] = {}
        existing = set(self.list_tab_names())
        requests = []
        for tab in SHEET_HEADERS:
            if tab not in existing:
                # Larger default grid so FXRates/Transactions do not hit 1000-row limit quickly
                requests.append(
                    {
                        "addSheet": {
                            "properties": {
                                "title": tab,
                                "gridProperties": {
                                    "rowCount": 10000,
                                    "columnCount": max(26, len(SHEET_HEADERS[tab]) + 4),
                                },
                            }
                        }
                    }
                )
        if requests:
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": requests},
            ).execute()
            for tab in SHEET_HEADERS:
                if tab not in existing:
                    status[tab] = "created"
        else:
            for tab in SHEET_HEADERS:
                status.setdefault(tab, "exists")

        for tab, headers in SHEET_HEADERS.items():
            action = self._ensure_header_row(tab, headers)
            if tab not in status or status[tab] == "exists":
                status[tab] = action
            elif action != "headers_ok":
                status[tab] = f"{status[tab]}+{action}"
        return status

    def _ensure_header_row(self, tab: str, headers: list[str]) -> str:
        """Write header row if missing/mismatched; preserve data rows when possible."""
        try:
            result = (
                self._service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{tab}'!A1:ZZ",
                    majorDimension="ROWS",
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"Cannot read tab {tab}: {exc}") from exc

        values = result.get("values") or []
        if not values:
            self._service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{tab}'!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ).execute()
            return "headers_written"

        current = [str(c).strip() for c in values[0]]
        if current == headers:
            return "headers_ok"

        data_rows = values[1:] if len(values) > 1 else []
        if not data_rows or not any(any(str(c).strip() for c in row) for row in data_rows):
            # empty sheet besides wrong header — safe full rewrite of header only
            self._service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{tab}'!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ).execute()
            return "headers_fixed"

        # Has data with different headers: fix header row only (do not clear body)
        self._service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{tab}'!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()
        logger.warning(
            "Tab %s had non-matching headers; header row updated in place "
            "(%d data rows left unchanged)",
            tab,
            len(data_rows),
        )
        return "headers_updated_in_place"

    # ------------------------------------------------------------------
    # Protocol
    # ------------------------------------------------------------------

    def list_rows(self, tab: str) -> list[SheetRow]:
        self._load_tab(tab)
        return list(self._cache[tab].values())

    def upsert_rows(self, tab: str, rows: list[SheetRow]) -> None:
        """Merge rows by id and patch only those sheet rows (not the full tab)."""
        if not rows:
            return
        self._load_tab(tab)
        expected = TAB_MODEL[tab]
        headers = SHEET_HEADERS[tab]
        bucket = self._cache[tab]
        index = self._row_index.setdefault(tab, {})
        updates: list[tuple[int, list[str]]] = []  # (1-based row, cells)
        appends: list[SheetRow] = []

        for row in rows:
            if not isinstance(row, expected):
                raise TypeError(
                    f"expected {expected.__name__} for {tab}, got {type(row).__name__}"
                )
            bucket[row.id] = row
            cells = model_to_row(row, headers)
            sheet_row = index.get(row.id)
            if sheet_row is None:
                appends.append(row)
            else:
                updates.append((sheet_row, cells))

        if updates:
            self._patch_rows(tab, updates)
        if appends:
            self._append_rows(tab, appends, headers)

        import time

        self._cache_loaded_at[tab] = time.time()
        self._dirty.discard(tab)

    def get_by_id(self, tab: str, row_id: UUID) -> SheetRow | None:
        self._load_tab(tab)
        return self._cache[tab].get(row_id)

    def find_statement_by_hash(self, content_sha256: str) -> StatementFile | None:
        needle = content_sha256.lower()
        for row in self.list_rows("StatementFiles"):
            assert isinstance(row, StatementFile)
            if row.archived:
                continue
            if row.content_sha256.lower() == needle:
                return row
        return None

    def delete_by_id(self, tab: str, row_id: UUID) -> bool:
        """Remove one row. Clears that sheet row in place (leaves a blank gap)."""
        return self.delete_by_ids(tab, [row_id]) == 1

    def delete_by_ids(self, tab: str, row_ids: list[UUID]) -> int:
        """
        Remove many rows in one (or few) patch batches.

        Prefer this over looping ``delete_by_id`` during lot rebuild so a partial
        failure cannot leave half-deleted stale lots next to newly upserted ones.
        """
        if not row_ids:
            return 0
        self._load_tab(tab)
        headers = SHEET_HEADERS[tab]
        blank = [""] * len(headers)
        index = self._row_index.setdefault(tab, {})
        updates: list[tuple[int, list[str]]] = []
        removed = 0
        for rid in row_ids:
            if self._cache[tab].pop(rid, None) is None:
                continue
            removed += 1
            sheet_row = index.pop(rid, None)
            if sheet_row is not None:
                updates.append((sheet_row, blank))
        if updates:
            self._patch_rows(tab, updates)
        import time

        self._cache_loaded_at[tab] = time.time()
        self._dirty.discard(tab)
        return removed

    def replace_all_rows(self, tab: str, rows: list[SheetRow]) -> None:
        """Replace an entire tab contents in one write (efficient bulk repair)."""
        expected = TAB_MODEL[tab]
        bucket: dict[UUID, SheetRow] = {}
        for row in rows:
            if not isinstance(row, expected):
                raise TypeError(
                    f"expected {expected.__name__} for {tab}, got {type(row).__name__}"
                )
            bucket[row.id] = row
        self._cache[tab] = bucket
        self._dirty.add(tab)
        self._flush_tab(tab)

    def flush_all(self) -> None:
        for tab in list(self._dirty):
            self._flush_tab(tab)

    def invalidate_cache(self, tab: str | None = None) -> None:
        if tab is None:
            self._cache.clear()
            self._cache_loaded_at.clear()
            self._row_index.clear()
            self._next_row.clear()
        else:
            self._cache.pop(tab, None)
            self._cache_loaded_at.pop(tab, None)
            self._row_index.pop(tab, None)
            self._next_row.pop(tab, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _tab_lock(self, tab: str):
        with self._tab_locks_guard:
            lock = self._tab_locks.get(tab)
            if lock is None:
                from threading import Lock

                lock = Lock()
                self._tab_locks[tab] = lock
            return lock

    def _tab_cache_fresh(self, tab: str) -> bool:
        import time

        if tab not in self._cache:
            return False
        # Never expire dirty tabs mid-write batch — local cache is source of truth
        if tab in self._dirty:
            return True
        loaded = self._cache_loaded_at.get(tab)
        if loaded is None:
            return False
        return (time.time() - loaded) < self._tab_cache_ttl_seconds

    def _load_tab(self, tab: str) -> None:
        if self._tab_cache_fresh(tab):
            return
        if tab not in SHEET_HEADERS:
            raise KeyError(f"unknown tab {tab}")
        with self._tab_lock(tab):
            # Second check after acquiring lock (another request may have loaded)
            if self._tab_cache_fresh(tab):
                return
            import time

            headers = SHEET_HEADERS[tab]
            try:
                result = (
                    self._service.spreadsheets()
                    .values()
                    .get(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"'{tab}'!A1:ZZ",
                        majorDimension="ROWS",
                    )
                    .execute()
                )
            except HttpError as exc:
                # Missing worksheet (new SHEET_HEADERS entry) → create and return empty
                msg = str(exc)
                if "Unable to parse range" in msg or (
                    getattr(getattr(exc, "resp", None), "status", None) == 400
                    and "parse range" in msg.lower()
                ):
                    logger.warning(
                        "Tab %s missing or unreadable; creating from schema: %s",
                        tab,
                        exc,
                    )
                    try:
                        self.ensure_tab(tab)
                    except Exception as create_exc:  # noqa: BLE001
                        logger.exception("Failed to create tab %s", tab)
                        raise RuntimeError(
                            f"Sheets tab {tab} missing and create failed: {create_exc}"
                        ) from create_exc
                    self._cache[tab] = {}
                    self._row_index[tab] = {}
                    self._next_row[tab] = 2
                    self._cache_loaded_at[tab] = time.time()
                    return
                logger.exception("Failed to read tab %s", tab)
                raise RuntimeError(f"Sheets read failed for {tab}: {exc}") from exc

            values = result.get("values") or []
            bucket: dict[UUID, SheetRow] = {}
            row_index: dict[UUID, int] = {}
            if not values:
                self._write_grid(tab, [headers])
                self._cache[tab] = bucket
                self._row_index[tab] = row_index
                self._next_row[tab] = 2  # first data row
                self._cache_loaded_at[tab] = time.time()
                return

            file_headers = [str(h).strip() for h in values[0]]
            # If empty or wrong headers, reset header row (keep data best-effort)
            if file_headers != headers:
                if not any(file_headers):
                    file_headers = headers
                # Use intersection order of expected headers
                use_headers = file_headers if "id" in file_headers else headers

            else:
                use_headers = headers

            # Sheet rows are 1-based; values[0] is header → data starts at row 2
            for offset, raw in enumerate(values[1:]):
                sheet_row = offset + 2
                if not raw or not any(str(c).strip() for c in raw):
                    continue
                try:
                    model = row_to_model(tab, use_headers, [str(c) for c in raw])
                    bucket[model.id] = model
                    row_index[model.id] = sheet_row
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Skipping bad row in %s: %s", tab, exc)
            self._cache[tab] = bucket
            self._row_index[tab] = row_index
            # Next free row is past the last physical row we saw (including blanks)
            self._next_row[tab] = max(len(values) + 1, 2)
            self._cache_loaded_at[tab] = time.time()

    def _flush_tab(self, tab: str) -> None:
        """Full clear+rewrite. Rebuilds row index. Prefer upsert_rows patch path."""
        headers = SHEET_HEADERS[tab]
        rows = list(self._cache.get(tab, {}).values())
        # Stable order by id string for deterministic sheets
        rows.sort(key=lambda r: str(r.id))
        grid = models_to_grid(tab, rows, headers)
        self._write_grid(tab, grid)
        # Rebuild id → sheet row map (header row 1, data from 2)
        self._row_index[tab] = {row.id: i + 2 for i, row in enumerate(rows)}
        self._next_row[tab] = len(rows) + 2
        self._dirty.discard(tab)
        import time

        self._cache_loaded_at[tab] = time.time()

    def _patch_rows(self, tab: str, updates: list[tuple[int, list[str]]]) -> None:
        """Write only the given sheet rows via values.batchUpdate."""
        if not updates:
            return
        # De-dupe by sheet row (last write wins) while preserving order
        by_row: dict[int, list[str]] = {}
        order: list[int] = []
        for sheet_row, cells in updates:
            if sheet_row not in by_row:
                order.append(sheet_row)
            by_row[sheet_row] = cells

        max_row = max(order)
        max_cols = max((len(c) for c in by_row.values()), default=26)
        self._ensure_grid_capacity(tab, min_rows=max_row, min_cols=max_cols)

        try:
            for i in range(0, len(order), self._PATCH_CHUNK):
                chunk_rows = order[i : i + self._PATCH_CHUNK]
                data = [
                    {
                        "range": f"'{tab}'!A{sheet_row}",
                        "values": [by_row[sheet_row]],
                    }
                    for sheet_row in chunk_rows
                ]
                req = (
                    self._service.spreadsheets()
                    .values()
                    .batchUpdate(
                        spreadsheetId=self.spreadsheet_id,
                        body={
                            "valueInputOption": "RAW",
                            "data": data,
                        },
                    )
                )
                execute_sheets_request(req, what=f"patch {tab}")
        except HttpError as exc:
            logger.exception("Failed to patch tab %s (%d rows)", tab, len(order))
            raise RuntimeError(f"Sheets patch failed for {tab}: {exc}") from exc

    def _sheet_meta(self) -> dict[str, dict[str, Any]]:
        """title -> {sheetId, rowCount, columnCount}."""
        meta = (
            self._service.spreadsheets()
            .get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)))",
            )
            .execute()
        )
        out: dict[str, dict[str, Any]] = {}
        for s in meta.get("sheets", []):
            props = s.get("properties") or {}
            title = props.get("title")
            if not title:
                continue
            grid = props.get("gridProperties") or {}
            out[str(title)] = {
                "sheetId": props.get("sheetId"),
                "rowCount": int(grid.get("rowCount") or 1000),
                "columnCount": int(grid.get("columnCount") or 26),
            }
        return out

    def _ensure_grid_capacity(
        self,
        tab: str,
        *,
        min_rows: int,
        min_cols: int | None = None,
    ) -> None:
        """
        Expand sheet grid when Google would reject writes past max rows/cols.

        Default Google sheets start with ~1000 rows; FXRates and Transactions
        grow past that during import / CNB backfill.
        """
        if min_rows < 2:
            return
        try:
            info = self._sheet_meta().get(tab)
        except HttpError as exc:
            logger.warning("Could not read sheet meta for %s: %s", tab, exc)
            return
        if not info or info.get("sheetId") is None:
            return

        need_rows = int(min_rows)
        # Headroom so the next bulk append does not re-hit the limit immediately
        target_rows = max(need_rows + 500, need_rows)
        # Soft cap — Google allows far more; avoid absurd expansions
        target_rows = min(target_rows, 500_000)

        need_cols = int(min_cols or 0)
        headers = SHEET_HEADERS.get(tab) or []
        if headers:
            need_cols = max(need_cols, len(headers) + 2)
        target_cols = max(int(info.get("columnCount") or 26), need_cols, 26)

        cur_rows = int(info.get("rowCount") or 0)
        cur_cols = int(info.get("columnCount") or 0)
        if cur_rows >= need_rows and cur_cols >= target_cols:
            return

        new_rows = max(cur_rows, target_rows)
        new_cols = max(cur_cols, target_cols)
        logger.info(
            "Expanding sheet grid %s: rows %s→%s cols %s→%s",
            tab,
            cur_rows,
            new_rows,
            cur_cols,
            new_cols,
        )
        try:
            req = self._service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": info["sheetId"],
                                    "gridProperties": {
                                        "rowCount": new_rows,
                                        "columnCount": new_cols,
                                    },
                                },
                                "fields": "gridProperties.rowCount,gridProperties.columnCount",
                            }
                        }
                    ]
                },
            )
            execute_sheets_request(req, what=f"expand {tab}")
        except HttpError as exc:
            logger.exception("Failed to expand grid for tab %s", tab)
            raise RuntimeError(
                f"Sheets grid expand failed for {tab} (need row {need_rows}): {exc}"
            ) from exc

    def _append_rows(self, tab: str, rows: list[SheetRow], headers: list[str]) -> None:
        """Append new models at the end of the tab and record their row indices."""
        if not rows:
            return
        index = self._row_index.setdefault(tab, {})
        next_row = self._next_row.get(tab, 2)
        # Expand grid before write (Google rejects A1007 when max rows is 1006)
        last_row_needed = next_row + len(rows) - 1
        self._ensure_grid_capacity(tab, min_rows=last_row_needed, min_cols=len(headers))
        # Contiguous block write is cheaper than N appends
        for i in range(0, len(rows), self._PATCH_CHUNK):
            chunk = rows[i : i + self._PATCH_CHUNK]
            start = next_row
            grid = [model_to_row(r, headers) for r in chunk]
            end_row = start + len(chunk) - 1
            try:
                req = (
                    self._service.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"'{tab}'!A{start}",
                        valueInputOption="RAW",
                        body={"values": grid},
                    )
                )
                execute_sheets_request(req, what=f"append {tab}@{start}")
            except HttpError as exc:
                # One structural retry after forced expand (stale meta / concurrent writer)
                err = str(exc)
                if "exceeds grid limits" in err or "grid limits" in err.lower():
                    logger.warning(
                        "Grid limit on %s row %s; expanding and retrying",
                        tab,
                        end_row,
                    )
                    self._ensure_grid_capacity(
                        tab, min_rows=end_row + 1000, min_cols=len(headers)
                    )
                    try:
                        req2 = (
                            self._service.spreadsheets()
                            .values()
                            .update(
                                spreadsheetId=self.spreadsheet_id,
                                range=f"'{tab}'!A{start}",
                                valueInputOption="RAW",
                                body={"values": grid},
                            )
                        )
                        execute_sheets_request(
                            req2, what=f"append-retry {tab}@{start}"
                        )
                    except HttpError as exc2:
                        logger.exception("Failed to append to tab %s after expand", tab)
                        raise RuntimeError(
                            f"Sheets append failed for {tab}: {exc2}"
                        ) from exc2
                else:
                    logger.exception("Failed to append to tab %s", tab)
                    raise RuntimeError(f"Sheets append failed for {tab}: {exc}") from exc
            for offset, row in enumerate(chunk):
                index[row.id] = start + offset
            next_row = start + len(chunk)
            # Pace large multi-chunk writes so we stay under ~60 writes/min
            if len(rows) > self._PATCH_CHUNK and i + self._PATCH_CHUNK < len(rows):
                time.sleep(1.05)
        self._next_row[tab] = next_row

    def _write_grid(self, tab: str, grid: list[list[str]]) -> None:
        body = {"values": grid}
        need_rows = max(len(grid), 1)
        need_cols = max((len(r) for r in grid), default=1)
        self._ensure_grid_capacity(tab, min_rows=need_rows, min_cols=need_cols)
        try:
            # Clear then write keeps sheet compact
            clear_req = self._service.spreadsheets().values().clear(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{tab}'",
                body={},
            )
            execute_sheets_request(clear_req, what=f"clear {tab}")
            update_req = self._service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{tab}'!A1",
                valueInputOption="RAW",
                body=body,
            )
            execute_sheets_request(update_req, what=f"write {tab}")
        except HttpError as exc:
            logger.exception("Failed to write tab %s", tab)
            raise RuntimeError(f"Sheets write failed for {tab}: {exc}") from exc


def build_repository_from_settings(
    settings: Any,
    *,
    user_credentials: UserCredentials | None = None,
    ensure_tabs: bool = False,
) -> GoogleSheetsRepository:
    """Factory: OAuth user creds preferred, else service account JSON.

    ``ensure_tabs`` defaults to False for request-path repos — header setup is
    expensive and belongs in the setup wizard / setup script only.
    """
    if user_credentials is not None and getattr(user_credentials, "token", None):
        creds: Any = user_credentials
    else:
        try:
            creds = credentials_from_service_account(
                json_path=getattr(settings, "google_application_credentials", None) or None,
                json_inline=getattr(settings, "google_service_account_json", None) or None,
            )
        except ValueError as exc:
            raise RuntimeError(
                "No Google credentials: place a service-account key at "
                "secrets/service-account.json, or set GOOGLE_APPLICATION_CREDENTIALS, "
                "or complete OAuth login (AUTH_MODE=oauth)."
            ) from exc
    return GoogleSheetsRepository(
        spreadsheet_id=settings.spreadsheet_id,
        credentials=creds,
        ensure_tabs=ensure_tabs,
    )
