"""Ensure categories, bootstrap rules, apply fill-blanks on live sheet."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from backend.config import get_settings
    from backend.services.categorization import bootstrap_rules_from_data, coverage_stats
    from backend.sheets.google_sheets import (
        GoogleSheetsRepository,
        credentials_from_service_account,
    )

    get_settings.cache_clear()
    s = get_settings()
    repo = GoogleSheetsRepository(
        s.spreadsheet_id,
        credentials_from_service_account(
            json_path=s.google_application_credentials or None,
            json_inline=s.google_service_account_json or None,
        ),
        ensure_tabs=False,
    )
    print("Bootstrapping…")
    result = bootstrap_rules_from_data(repo, also_apply=True)
    print(result)
    cov = coverage_stats(repo, days=180)
    print(
        f"Coverage {cov['coverage_pct']:.1f}% · "
        f"{cov['expense_usd_categorized']} / {cov['expense_usd_total']} · "
        f"rules={cov['rules_count']} cats={cov['categories_count']}"
    )
    print("Top uncategorized:")
    for m in cov["top_uncategorized_merchants"][:12]:
        print(f"  {m['amount_usd']:>10}  {m['label'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
