# Gauntlet Finance — Build Log

Incremental notes per PR. Deviations from Collective are recorded here.

---

## 2026-08-10 — Fix 1D chart at market open

- 1D fetch uses **5d×5m** then trims (US RTH today / prior session; portfolio+crypto last 24h).
- Split equity vs crypto Yahoo batches; softer **50%** intraday coverage; don’t long-cache empty/short 1D.
- UI: session_status copy + clearer empty-session message.

## 2026-08-10 — Buy/sell markers on live portfolio chart

- `/prices/history` meta.trades: statement Buy/Sell in window (no staking); `series_value` snaps to MV/price line.
- Holdings + Analysis charts: green/red scatter, tooltip, toggle (localStorage).

## 2026-08-10 — Portfolio chart: holdings as-of each date

- **Bug:** `scope=all` / `asset_class` MV history used **current open-lot qty × historical prices**, inflating past MV (e.g. 2021 showed today’s book marked at 2021 prices).
- **Fix:** rebuild qty from statement `InvestmentEvents` (Buy/Sell/StakingReward/Split/exit Transfer); `MV(t) = Σ qty(as_of date(t)) × price(t)`. Coverage gate uses then-owned book. Meta `quantity_basis=holdings_as_of_each_date`.
- Module: `holdings_timeline.py`; aggregate `aggregate_mv_series_time_aware`.

## 2026-08-10 — DCA board color coding

- Ticker chips + score bars use Desk palette tiers: **hot** (ok/green), **strong** (brand), **warm** (warn), **cool/watch** (muted) — not monochrome.

## 2026-08-10 — DCA board view (Investments)

- `/investments/dca` — dual lists (Stocks | Crypto) ranked by continuous opportunity score.
- API `GET /investments/dca-opportunities`; shared scoring with alerts; Active vs Watch gates.

## 2026-08-10 — DCA opportunity alerts

- New alerts on open holdings: **Signal A** mark clearly below avg cost (stock ≥10% / crypto ≥18%); **Signal B** 3M pullback and/or **drawdown below 52-week average** (stock ≥5% / crypto ≥10% under mean), while not extended >5% above book cost.
- Gates: min position $400, 21d buy cooldown, skip if weight >35%, stale price >7d. Top 3 by score; deep discounts → `warn`.
- Yahoo 1y history fail-open (process cache); statement lots + Prices only required for Signal A.
- Tests: `backend/tests/test_alerts_dca.py`. Cache key `alerts:v3`.

## 2026-08-09 — Live marks for all wealth KPIs

- `DrawMetricsCard` + Analysis snapshot soft-reload on `prices-updated` (no blank spinner).
- Dashboard already reloads snapshot (MV, unrealized, tax-free runway); draw/safe capacity now track 60s soft price poll too.

## 2026-08-09 — Chart polish: soft 1D refresh, 7D, live dashboard MV

- Soft re-fetch keeps prior series (no blank flash); larger total/change/cost type.
- Ranges: drop MAX; add **7D**. Layout soft-polls `refreshPrices(false)` every 60s on Dashboard/Investments when tab visible.

## 2026-08-09 — Fix: timeframes collapsed by short-history tickers

- Root cause: requiring **all** priced names before any MV point made SPCX-like listings (first bar mid-2026) clip 3M–MAX to ~39 days.
- Fix: emit when **≥90% of book weight** (qty × latest px) is marked; late listings join mid-series; meta `short_history_tickers`.
- UTC-normalize intraday timestamps for stable sort (stock vs crypto TZ).

## 2026-08-09 — Fix: empty stock history + low collective MV start

- Root cause: yfinance MultiIndex columns (`(Ticker,Close)` / `(Close,Ticker)`); single-ticker path treated Close as flat Series → empty history.
- Root cause 2: aggregate MV emitted partial sums before all priced names had a first bar → ridiculously low early values.
- Fix: robust Close extraction + coverage-threshold aggregate (superseded all-names wait).

## 2026-08-09 — Chart v2: 1D, pop-out, Analysis MV without snapshots

- History ranges add **1D** (5m bars); meta includes **today** open/last/change for any range.
- Scope **`all`** = full portfolio mark series; Analysis `PortfolioMvChart` uses `/prices/history` (not `PortfolioSnapshots`).
- **Pop out** → `/investments/chart` chrome-free window; auto-refresh 60s on 1D.
- Price refresh **no longer writes** portfolio snapshots; job `portfolio-snapshot` returns deprecated.

## 2026-08-09 — Position price history chart (Google Finance–style)

- `GET /api/prices/history?scope=ticker|asset_class|all&range=…` — yfinance daily/5m bars, process cache.
- Scopes: ticker; Stock/Crypto books; full portfolio — current holdings × historical prices.
- Holdings chart + pop-out; avg-cost / cost-basis reference line. No OHLCV in Sheets.


## 2026-08-08 — Fix: PortfolioSnapshots missing tab 500

- Root cause: `PortfolioSnapshots` not in live spreadsheet; `list_rows` raised on parse range.
- `GoogleSheetsRepository._load_tab` auto-creates missing schema tabs; `list_mv_series` returns empty on failure.

## 2026-08-08 — Wave 4: year-end export pack

- `GET /api/exports/year-end?year=` → ZIP (tax JSON/CSV, open lots, gains-by-year, category spend, statement files, README).
- UI: Investments → Tax “Year-end pack”; Settings download with year picker.

## 2026-08-08 — Wave 3: rule suggestions + split investments page

- `GET /api/categories/rule-suggestions` — ranked residuals with category affinity.
- Merchant queue pre-fills suggested categories; Categorize shows Suggested rules panel.
- Investments analysis widgets split to `frontend/src/features/investments/*` (page re-exports).

## 2026-08-08 — Wave 2: MV series + living vs safe draw

- Tab `PortfolioSnapshots`; record on price refresh + job `portfolio-snapshot`.
- `GET /api/investments/mv-series`, `draw-metrics`; Analysis charts; Dashboard compact draw card.
- Safe draw = min(4% × MV, tax_free_now_usd) vs 12m living draw (sells − buys).

## 2026-08-09 — Spending chart residual bar rename

- Chart rollup of categories outside top‑N was labeled **Other (N)**, colliding with Uncategorized/Other domain.
- Renamed to **Smaller categories (N)**; tooltip clarifies; top N raised to 25; Categorize chips match.

## 2026-08-09 — Self-education category

- New top-level **Self-education** (`LifeDomain.Education`), stable id `CAT_SELF_EDUCATION`.
- Seed rule: `original_description` **exact** `CEZARY BIERNAT` (course payment) — not account-holder contains.
- `ensure-defaults` seeds rule + reclassifies matching rows (e.g. was External transfer).

## 2026-08-09 — Realized windows show sold cost basis

- FIFO lifetime economics: `realized_cost_basis_usd`, `realized_proceeds_usd`, `realized_roi_pct` on portfolio snapshot + ticker digests (`proceeds − gain` from LotAllocations).
- Investments Realized KPI hover/card + Dashboard + ticker detail: “gain on $cost sold · +ROI%”.

## 2026-08-09 — Open app on Dashboard

- Cold session landing on `/settings` (common iOS home-screen / tab restore after setup) redirects once to `/`.
- Brand header links home; OAuth callback → site root; PWA manifest `scope`/`id` set to `/`.

## 2026-08-09 — Transfer-leak false positives (peer P2P)

- Live diagnosis: remaining “unflagged transfers” were **peer** Revolut rows (`Transfer to NAME`) already in **Going out / Fitness**.
- Resolve `transfer_leak` for any non-Other category (or `category_override`), not only Transfers/Investments.
- Alert copy clarifies uncategorized/Other only; Categorize filter matched.

## 2026-08-08 — Tax nav + transfer-leak alerts

- **Nav:** Investments → **Tax** leaf in main sidebar (`Layout.tsx`).
- **Alerts:** `transfer_leak` no longer sticks after review — clears when row is internal **or** categorized into Transfers/Investments / `is_transfer` category (not only when `is_internal_transfer`).
- **Categorize:** drill-down filter matches that rule; assigning **Internal transfer** also sets `is_internal_transfer=true` (single + bulk override).
- Tests: `backend/tests/test_alerts_transfer_leak.py`.

## 2026-08-08 — Wave 1: Tax UI + import reliability

- Tax: `/tax-report/years`, `/summary-by-year`, CSV export; UI at **Investments → Tax**.
- Gains-by-year stacked bar (taxable vs exempt CZK).
- Statement files: `GET /statement-files`, `POST …/retry`; upload bytes stored under `data/uploads` (or `UPLOAD_STORE_DIR`).
- Upload page: import history + Retry for Error/Pending when bytes present.

## 2026-08-08 — F9 background FX jobs

- `backend/services/jobs.py`: registry, single-flight per kind, `fx-fetch-cnb` / `fx-backfill-amounts` / `fx-full`.
- Admin: `GET/POST /api/admin/jobs…`, `POST /api/admin/jobs/tick` + `CRON_SECRET`.
- Settings UI: run buttons + recent job table.

## 2026-08-08 — F8 consistent `/api` prefix

- Domain routers mounted under `/api/*`; `/health` + `/api/health`.
- Setup wizard remains `/setup` (+ `/setup/api/*`).
- Vite proxy no longer strips `/api`; Docker `VITE_API_BASE=/api`.
- SPA catch-all only outside api/docs/setup/health — fixes deep links vs API collision.
- OAuth default redirect: `/api/auth/callback`.

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
