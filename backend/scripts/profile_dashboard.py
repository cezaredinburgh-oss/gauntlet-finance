"""Quick timing for dashboard hot path."""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> None:
    from backend.config import get_settings
    from backend.services.alerts import build_alerts
    from backend.services.dashboard import dashboard_summary
    from backend.services.portfolio_snapshot import portfolio_snapshot
    from backend.sheets.google_sheets import (
        GoogleSheetsRepository,
        credentials_from_service_account,
    )

    get_settings.cache_clear()
    s = get_settings()
    t0 = time.perf_counter()
    repo = GoogleSheetsRepository(
        s.spreadsheet_id,
        credentials_from_service_account(
            json_path=s.google_application_credentials or None,
            json_inline=s.google_service_account_json or None,
        ),
        ensure_tabs=False,
    )
    print(f"repo init {time.perf_counter() - t0:.2f}s")

    t0 = time.perf_counter()
    d = dashboard_summary(
        repo,
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 5),
        period_key="this_month",
        persist_fx=False,
    )
    print(
        f"dashboard cold {time.perf_counter() - t0:.2f}s "
        f"income={d['cashflow']['income_usd']} expense={d['cashflow']['expense_usd']}"
    )

    t0 = time.perf_counter()
    d2 = dashboard_summary(
        repo,
        date_from=date(2026, 7, 1),
        date_to=date(2026, 7, 31),
        period_key="last_month",
        persist_fx=False,
    )
    print(
        f"dashboard re-range {time.perf_counter() - t0:.2f}s "
        f"net={d2['cashflow']['net_usd']}"
    )

    t0 = time.perf_counter()
    p = portfolio_snapshot(repo)
    print(f"snapshot {time.perf_counter() - t0:.2f}s mv={p['total_market_value_usd']}")

    t0 = time.perf_counter()
    a = build_alerts(repo, persist_fx=False)
    print(f"alerts {time.perf_counter() - t0:.2f}s n={a['total']}")


if __name__ == "__main__":
    main()
