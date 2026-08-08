#!/usr/bin/env python3
"""
Idempotent Google Sheet tab setup for Collective Finance.

Prerequisites (see docs/GOOGLE_SHEETS_SETUP.md):
  1. Service account JSON at secrets/service-account.json
  2. SPREADSHEET_ID in .env (or pass --spreadsheet-id)
  3. Spreadsheet shared with the service account email as Editor

Usage (from project root):
  python -m backend.scripts.setup_google_sheet
  python -m backend.scripts.setup_google_sheet --seed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root on path when run as script
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _print(msg: str) -> None:
    print(msg, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create finance app tabs in a Google Sheet")
    parser.add_argument(
        "--spreadsheet-id",
        default=None,
        help="Override SPREADSHEET_ID (also accepts full Google Sheets URL)",
    )
    parser.add_argument(
        "--credentials",
        default=None,
        help="Path to service-account JSON (default: secrets/service-account.json)",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Also write minimal seed Accounts/Categories/Settings if empty",
    )
    parser.add_argument(
        "--no-ensure-on-connect",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    from backend.config import get_settings
    from backend.schema.models import SHEET_HEADERS
    from backend.sheets.google_sheets import (
        build_repository_from_settings,
        credentials_from_service_account,
        service_account_email,
    )

    get_settings.cache_clear()
    settings = get_settings()

    spreadsheet_id = args.spreadsheet_id or settings.spreadsheet_id
    if spreadsheet_id and "/d/" in spreadsheet_id:
        spreadsheet_id = spreadsheet_id.split("/d/")[1].split("/")[0]
    creds_path = args.credentials or settings.google_application_credentials

    _print("=" * 72)
    _print("Collective Finance — Google Sheet setup")
    _print("=" * 72)

    # --- Validate credentials ---
    try:
        email = service_account_email(
            json_path=creds_path,
            json_inline=settings.google_service_account_json or None,
        )
        _print(f"[OK] Service account key loaded")
        _print(f"     client_email: {email}")
        _print(f"     Share your spreadsheet with this email as Editor.")
    except Exception as exc:  # noqa: BLE001
        _print(f"[FAIL] Cannot load service account credentials: {exc}")
        _print("")
        _print("Fix:")
        _print("  1. Create a service account key in Google Cloud Console")
        _print("  2. Save it as: secrets/service-account.json")
        _print("  3. Or set GOOGLE_APPLICATION_CREDENTIALS in .env")
        return 1

    if not spreadsheet_id or not str(spreadsheet_id).strip():
        _print("[FAIL] SPREADSHEET_ID is empty")
        _print("")
        _print("Fix:")
        _print("  1. Create a Google Spreadsheet in the browser")
        _print("  2. Copy the ID from the URL:")
        _print("     https://docs.google.com/spreadsheets/d/<THIS_PART>/edit")
        _print("  3. Put it in .env as SPREADSHEET_ID=...")
        return 1

    _print(f"[OK] Spreadsheet ID: {spreadsheet_id}")

    # Patch settings for this run
    object.__setattr__(settings, "spreadsheet_id", spreadsheet_id)
    if creds_path:
        object.__setattr__(settings, "google_application_credentials", creds_path)

    # --- Connect ---
    try:
        creds = credentials_from_service_account(
            json_path=creds_path,
            json_inline=settings.google_service_account_json or None,
        )
        from backend.sheets.google_sheets import GoogleSheetsRepository

        repo = GoogleSheetsRepository(
            spreadsheet_id=spreadsheet_id,
            credentials=creds,
            ensure_tabs=False,
        )
        _print("[OK] Connected to Google Sheets API")
    except Exception as exc:  # noqa: BLE001
        _print(f"[FAIL] Connection error: {exc}")
        _print("")
        _print("Common causes:")
        _print("  - Google Sheets API not enabled on the Cloud project")
        _print("  - Spreadsheet not shared with the service account email")
        _print("  - Wrong SPREADSHEET_ID")
        return 1

    # --- Ensure tabs + headers ---
    try:
        tab_status = repo.ensure_all_tabs()
        _print("")
        _print("Tabs:")
        for tab in SHEET_HEADERS:
            st = tab_status.get(tab, "?")
            mark = "OK" if "ok" in st or st == "created" or "written" in st or "fixed" in st or "updated" in st or st == "exists" else "??"
            # normalize display
            if st in {"headers_ok", "exists"}:
                mark = "OK"
                st = "ready"
            elif st == "created" or "created" in st:
                mark = "NEW"
            elif "headers" in st:
                mark = "OK"
            _print(f"  [{mark}] {tab:20} {st}")
            cols = ", ".join(SHEET_HEADERS[tab][:6])
            _print(f"         columns ({len(SHEET_HEADERS[tab])}): {cols}, …")
    except Exception as exc:  # noqa: BLE001
        _print(f"[FAIL] Tab setup error: {exc}")
        return 1

    names = repo.list_tab_names()
    missing = [t for t in SHEET_HEADERS if t not in names]
    if missing:
        _print(f"[FAIL] Still missing tabs: {missing}")
        return 1

    _print("")
    _print(f"[OK] All {len(SHEET_HEADERS)} required tabs are present")
    _print(f"     Sheet tabs now: {', '.join(names)}")

    # --- Optional seed ---
    if args.seed:
        try:
            from backend.scripts.seed_dev_repo import seed_minimal

            seed_minimal(repo)
            _print("[OK] Minimal seed data written (Accounts/Categories/Rules/FX/Settings if empty)")
        except Exception as exc:  # noqa: BLE001
            _print(f"[WARN] Seed failed (tabs are still fine): {exc}")

    _print("")
    _print("=" * 72)
    _print("SUCCESS — Sheet is ready for the API")
    _print("=" * 72)
    _print("Next:")
    _print("  1. Confirm .env has:")
    _print(f"       AUTH_MODE=dev")
    _print(f"       SPREADSHEET_ID={spreadsheet_id}")
    _print(f"       GOOGLE_APPLICATION_CREDENTIALS=secrets/service-account.json")
    _print("  2. Start API:")
    _print("       $env:PYTHONPATH=\".\"")
    _print("       uvicorn backend.api.main:app --reload --port 8000")
    _print("  3. Verify:")
    _print("       curl http://localhost:8000/health")
    _print("       curl http://localhost:8000/sheets/status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
