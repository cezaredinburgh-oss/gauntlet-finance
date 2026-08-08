#!/usr/bin/env python3
"""
REMOVED — external desk ledger import is forbidden.

Hard rule: all bank / broker holdings data must come only from files under
  Collective personal finance app/Bank statements/

Do not import from portfolio_desk, other iCloud folders, or manual TSVs outside
this project.

To rebuild open lots from statement imports already in the sheet:
  python -m backend.scripts.purge_non_statement_lots
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "[BLOCKED] repair_lots_from_desk_ledger is disabled.\n"
        "Hard rule: do not load bank/broker data from outside\n"
        "  <project>/Bank statements/\n"
        "Use instead:\n"
        "  python -m backend.scripts.purge_non_statement_lots\n"
        "or re-upload files from Bank statements via the app Upload page."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
