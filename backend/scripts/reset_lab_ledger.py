"""Reset the persistent lab test account to an empty new-user surface.

Usage (repo root)::

    python -m backend.scripts.reset_lab_ledger --dry-run
    python -m backend.scripts.reset_lab_ledger

Wipes ``LAB_DATA_DIR/ledger.json`` and re-seeds public categories only.
Does not touch Google Sheets or the owner ledger.
"""

from __future__ import annotations

import argparse
import json
import sys

from backend.config import get_settings
from backend.services.lab_account import reset_lab_ledger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report current lab stats without deleting",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.lab_login_enabled and not args.dry_run:
        print(
            "LAB_LOGIN_ENABLED is false; reset still allowed (disk wipe only).",
            file=sys.stderr,
        )
    result = reset_lab_ledger(settings, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
    if args.dry_run:
        return 0
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
