# Gauntlet Finance — Build Log

Incremental notes per PR. Deviations from Collective are recorded here.

---

## 2026-08-08 — Analysis: CZK/USD chart + portfolio FX context

- `GET /fx/usd-czk` — CNB series from FXRates; optional `portfolio_usd` adds CZK wealth path.
- Investments **Analysis** page: timeframe picker (same control as dashboard) + dual-axis chart (rate + portfolio in CZK).
- Portfolio context: holds **today’s USD MV** fixed and revalues in CZK at each day’s rate → pure FX effect on the CZK reading of wealth.

## 2026-08-08 — Historical FX + native row display

- **Bug:** UI secondary CZK used hardcoded `23.1` when `amount_czk` missing (e.g. Murariu −$854.46 → fake ≈19,738 Kč).
- **Display rule:** rows show statement-native currency; secondary only from stored historical legs; dashboard/spend totals stay USD.
- **Backend:** import enriches new cash txs with `amount_usd`/`amount_czk` via CNB on `booking_date`; backfill prioritizes missing either leg + optional CNB self-heal (`ensure_fx_coverage`).
- **Ops:** `POST /admin/fetch-cnb` then `POST /admin/backfill-fx` (or CLI scripts) after large reimports.
- Removed `DISPLAY_USD_CZK` / `estimateCzkFromUsd` invent path from frontend.

## 2026-08-07 — Phase 0 design gauntlet

- Wrote `docs/GAUNTLET_DESIGN.md` (reconstructed from Collective; blueprint missing).
- Adversarial review → `docs/GAUNTLET_DESIGN_REVIEW.md`.
- Three write/review rounds; **35** issues addressed; **0** open.
- Defaults recorded for open product questions (OQ-1…OQ-4) in design.

## 2026-08-07 — PR1–PR3 scaffold through FX

- Ports **8020** / **5190**, `gf_session`, health, UI shell, Start-App.
- Schema, InMemory, Fitness/My business, Digital Assets rule priority 6.
- Money/hash/time, FXService, fx_amounts.

## 2026-08-07 — PR4–frontend

- Engines, parsers, Sheets, import pipeline, portfolio services, full API routes.
- React UI port (Collective → Gauntlet branding).
- pytest 126+ green; frontend build clean.

## 2026-08-07 — Launcher: no residual console windows

- `Start-App.bat` detaches hidden PowerShell and exits immediately.
- `Start-App.ps1` CreateNoWindow for API/UI; MessageBox on failure.
- Fixed silent fail (Unicode parse errors; path spaces).

## 2026-08-08 — Overlapping import dedupe

- Event soft keys: no `original_file_hash`; second-resolution UTC; norm decimals.
- Crypto/stocks stable `ext:Revolut:…` external_id.
- Expenses: no Balance in hash; soft keys include wall-clock times; soft∪hard for Balance migration.
- Upload message: `N parsed · X already in ledger · Y new`.
- `repair_duplicate_investment_events.py` + rebuild lots runbook.
- pytest **145** passed. Crypto 99.2% / stocks 98.7% / checking 97.3% overlap drop.

## 2026-08-08 — Setup & deploy wizard (Sheets + GitHub + Railway)

- Wizard steps 1–8: Cloud, key, **create spreadsheet**, share/test, prepare ledger, local check, GitHub, deploy env export.
- `POST /setup/api/create-spreadsheet`, `prepare-ledger`, `GET /setup/api/deploy-env`.
- Production SPA serve from `frontend/dist`; multi-stage `Dockerfile`, `railway.toml`, `render.yaml`.
- Scripts: `Prepare-GitHub.ps1`, `Export-DeploySecrets.ps1`; docs: `DEPLOY.md`.

## 2026-08-08 — Cashflow chart: multi-year non-USD history

**Problem:** Bars only used `value_usd`; Revolut CZK (etc.) legs left it null → chart looked empty before ~2 years of USD-filled rows.

**Fix:** Resolve cashflow notional via value_usd → value_native if USD → FX convert; pass FX from portfolio snapshot. Trim leading zero months on auto window.

## 2026-08-08 — Buy vs sell chart: proceeds coverage (not unbounded reinvest %)

**Problem:** Gold line used `cum_buys / cum_sells`, which explodes when buys happen with little selling and crushed the bar scale toward zero.

**Change:**
- Backend: `proceeds_coverage_pct = min(cum_buys, cum_sells) / cum_sells * 100` (0–100); `cumulative_net_capital_usd`; keep unbounded ratio for API compat only.
- Chart: plot coverage on fixed 0–100% right axis; optional dashed monthly rate (null when no sells, plot-capped 150%); KPI “Proceeds covered”.

**Tests:** `test_cashflow_monthly_cumulative_reinvest`, `test_cashflow_proceeds_coverage_partial_and_null_before_sells`.

## 2026-08-08 — Buy vs sell chart: bars only, colors, timeframe memory

**UI:** Drop gold coverage / dashed monthly rate lines and right % axis. Bars only — Bought `#34d399`, Sold `#e07a5f`. KPI tiles: last-month bought/sold/net (3 tiles). Tooltip: bought/sold/net. Discreet pill timeframe `6m | 12m | 24m | All` (default 24m); client-side slice; `localStorage` key `gauntlet.investments.cashflow.months`.

**Backend:** `compute_cashflow_monthly(months=None)` auto-window from first Buy/Sell through `as_of`, cap **120** months (snapshot path). Explicit `months=N` unchanged for unit tests.

**Tests:** existing months=2 cases; `test_cashflow_monthly_auto_history_spans_years`.
