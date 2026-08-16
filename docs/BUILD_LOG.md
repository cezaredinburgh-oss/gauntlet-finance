# Gauntlet Finance — Build Log

Incremental notes per PR. Deviations from Collective are recorded here.

---

## 2026-08-16 — Lab reset wipes numbered snapshots

- `reset_lab_ledger` now deletes every `ledger*.json` in the lab data dir (canonical + iCloud numbered copies) and reseeds without recover, so a wipe cannot be undone by the next boot.
- `ok` requires zero Transactions / lots / events / StatementFiles and a non-empty public category pack.
- Intentional reset still does not touch Google Sheets or `%LOCALAPPDATA%\\GauntletFinance\\icloud-ledger-archive`.
- Lab password login on an empty ledger resets first-run client state (onboarding, Categorize wizard, Grok+ session) so it behaves like a brand-new user.
- Landing no longer hides the lab form when open-auth auto-signs you in as Dev User. Switch-account form prefills the lab email. Start-App opens `127.0.0.1` (same host as Vite) so cookies are not split from `localhost`.
- Lab login 503 “set LAB_PASSWORD” was a production hard-block, not a missing secret. Single-tenant hosts honor `LAB_*`. Error text matches the real reason.
- Lab password login is allowed on multi-tenant production when `LAB_*` is set. Storage is the Railway volume (`/data/lab`), not a shared Sheets tenant. OAuth users stay isolated.
- `POST /api/lab/reset` (confirm `WIPE LAB`) wipes the lab ledger **in the running API process** so Railway `/data/lab` can be emptied. Local CLI reset never touched that volume.

---

## 2026-08-15 — Lab ledger survives iCloud rename

- iCloud Drive was renaming `data/lab/ledger.json` to `ledger 2.json` … `ledger 103.json` on each save. Restart then loaded an empty ledger, so coverage collapsed after re-import.
- Lab data now lives under local AppData when the repo is on iCloud/OneDrive. Startup recovers the newest numbered `ledger*.json` if the canonical file is missing.
- Production ignores `LAB_LOGIN_ENABLED` (shared JSON is not a per-user store). Real tenants stay on Google Sheets.

---

## 2026-08-15 — New ET becomes Expense tracking

- Removed the legacy Spending / Groups / AI-desk Categorize UI.
- `/expenses/spending` and `/expenses/categorize` mount the former New ET pages for every account. `/new-et/*` redirects. Lab gate gone.
- Alerts is a top-level nav item at `/alerts` (same level as Upload and Settings). `/expenses/alerts` redirects.
- Grok+ is on for all accounts (still user-started and suggest-only).
- Rest-of-app chrome: working banners on quotes / Map with Grok; Alerts + Tax Retry; empty Holdings/Tax CTAs; onboarding copy matches vendor-first + Grok+.

---

## 2026-08-14 — Categorize feedback 2

- First assign is quiet; **Recategorized** only after a second human change.
- Rules table sorts by column. Vendor rows have Skip; Apply all advances to a new set.
- Assigned vendors leave the list. New-user wizard is exclusive until finished or skipped.

## 2026-08-14 — Categorize coaching UX

- New-user wizard (categories → vendors → short Grok+ tour); skip allowed.
- First Grok+ leftover run is one batch. Chip can be closed.
- Create category from vendor / Grok+ lists. Approve shows progress.
- Coverage is full-ledger; est. leftover $ to 50/75/90%. Wipe assigns + memory only.

## 2026-08-14 — Tag on upload + VendorMemory

- Import no longer writes `category_id`. Core pack tags only; structural own-money sets `is_internal_transfer`.
- Tiny exact shops: Spotify, Netflix, McDonald’s. No owner-name rule on ensure-defaults.
- User assigns learn `VendorMemory`. Grok+ proposes those after two confirms, then tags, then leftover Grok.

## 2026-08-14 — Grok+ background loop + floating chip

- Ask Grok+ now keeps matching leftover residuals in a lab-only Layout session (not a 3-batch click).
- A bottom-right chip follows the user around the app: status, latest match, session + today cost estimate, jump back to Approve.
- Hidden tab pauses; Pause/Resume on the chip. Suggest-only. 80-batch session cap.
- Cost is an estimate from published grok-4.3 / 4.5 rates × prompt/completion tokens (day total uses quota × 80/20 blend).
- Approve selected no longer wipes remaining guesses.

## 2026-08-13 — Ask Grok+: remap groups and approve selected

- Category rows are editable (e.g. Fuel (car) → Moto fuel); vendors regroup immediately.
- Groups are ticked by default. Untick anything that still needs work, then **Approve selected**.

## 2026-08-13 — Ask Grok+ hybrid: local sort, then leftover Grok

- Residual vendors are compiled in memory (not disk files).
- Cheap rules map pots/FX/ATM/loans/fees and known shops first.
- Grok sees leftovers only (no web_search tools); unmatched stay empty and show as **Unmatched**.
- Local matches survive a Grok timeout.

## 2026-08-13 — Ask Grok+ timeout: short knowledge batches

- Root cause: `chat/completions` 422s on `web_search` tools, then one huge plus payload hit a 60s ReadTimeout.
- Plus is now 12 searchable vendors per call, no tools, 45s, knowledge prompt (do not browse).
- UI runs 3 sequential batches and paints the category table after each; a later timeout keeps earlier matches.

## 2026-08-13 — Ask Grok+: category table, then vendors, then txs

- **Ask Grok+** still matches full-ledger uncategorized vendors to your categories.
- UI is now a **category table** (name + comma-separated vendors). Click a category to expand vendors; click a vendor to load transactions.

## 2026-08-13 — Ask Grok+: categories with assigned vendors

- Shortcuts **Ask Grok+** researches up to 80 full-ledger uncategorized vendors and lists them **under each category**.
- Same Apply / Apply + rule / Apply all per category. Table stays empty until a vendor is clicked.

## 2026-08-13 — Ask Grok: hide table until click; full-ledger vendors; unstick filters

- Transaction table stays empty in Ask Grok until a vendor row is clicked.
- `/ai/vendor-suggest` ignores page date/filter and ranks uncategorized vendors across the whole ledger.
- Active-filter and bulk-assign bars no longer stick on scroll.

## 2026-08-13 — Vendor lists: Apply all / Apply all + rules, then next 10

- Both By vendor and Grok cards have **Apply all** and **Apply all + rules** for the current 10 with a category.
- After the batch (or the last remaining row) Grok fetches the next 10; By vendor just shows the next residual merchants.

## 2026-08-13 — Ask Grok: route was missing; list now appears immediately

- Start-App had loaded the API *before* `/api/ai/vendor-suggest` existed, so the button 404’d with no list.
- UI now shows the top searchable merchants immediately, falls back to `/ai/categorize-suggest` on 404, and Grok retries without web-search tools if search times out.

## 2026-08-13 — Ask Grok looks up merchants, not pot-to-pot narratives

- Prompt is now: web-search what the business is, then pick from the app category list. Not “assign a category to a blob.”
- Send-set drops vault / pocket / exchanged-to / incoming-payment rows and prefers named merchants (Lime, Rohlik, …).

## 2026-08-13 — New ET Ask Grok vendors + Apply & rule

- Shortcuts **Ask Grok**: top 10 residual vendors, Grok web search, suggested category + reason. Suggest-only; no lab heuristic.
- **By vendor** and Grok lists: 10 at a time (next/prev). Each row has **Apply** and **Apply + rule**.

## 2026-08-13 — Coverage counter is full-ledger, not the 3k table page

- Review table still loads newest 3,000 (hide-transfers). The widget counted that page, so ~2,700 uncategorized looked like the whole book.
- `coverage_stats` now returns `tx_categorized` / `tx_uncategorized` over the full ledger (internals skipped). Widget uses those, with an optimistic nudge on assign.

## 2026-08-13 — New ET coverage widget is live

- Widget was last-180d expense $ from the API, so assigning a vendor pile (often older than 180d) looked frozen.
- Coverage now counts the loaded list: live % plus **categorized / uncategorized** tx counts. Top uncategorized is the same residual vendor rollup.

## 2026-08-13 — New ET vendor pick no longer re-renders the table

- Cause: vendor category `<select>` wrote parent state, so one change reconciled ~3k table rows × every category `<option>`.
- Fix: each vendor row owns its pick locally (`React.memo`). Apply enables in the same paint.

## 2026-08-13 — New ET Shortcuts: By vendor rollup

- Shortcuts **By vendor** lists residual merchants as one row each (`McDonalds ×18`), count-desc.
- Click the name to focus those rows in the table. Category + **Apply ×N** mass-assigns the pile, then the usual next-steps card.

## 2026-08-13 — New ET: drop AI desk, flatten assign → similar → rule

- Removed New ET Review AI (Suggest clusters, presets, chat). Old `/expenses/categorize` AI unchanged.
- After assigning a category, one **Next steps** card shows three actions side by side: **Review similar**, **Apply to N similar**, **Apply + save rule**.
- High-confidence path is one click: apply remaining residual matches and write the suggested rule.

## 2026-08-13 — New ET easy-pile shortcuts (chat removed)

- Dropped the Review chat box. Next to **Suggest clusters**: **Top 5 vendors** (by residual tx count), **Internal transfers**, **Fees / ATM**, **Uncategorized income**.
- `POST /ai/categorize-presets` is deterministic (no Grok). Bundles matching rows so Show / Apply work even when they sit outside the newest-3000 table.
- Internal shortcut apply still sets `is_internal_transfer`. Already-flagged internals are skipped.

## 2026-08-13 — New ET “Ask Grok” chat + grocery-biased residual search

- Review had a chat box (`POST /ai/categorize-ask`). Query tokens + grocery/food hints rank residuals; large unique transfers are not the default send-set. **Superseded:** chat UI removed; endpoint unused by New ET.
- Default Suggest also down-ranks transfer-like vendor groups (Revolut/Raiffeisen/top-up).

## 2026-08-13 — Cluster easy vendors first; Show merges rows into the table

- Residual send-set is ranked by **repeat vendor count**, not largest amount. Prompt tells Grok the same.
- **Show transactions** merges hydrated/bundled rows into `items` and matches focus ids case-insensitively (empty table bug).

## 2026-08-13 — New ET cluster apply by id (not table page)

- Cluster **Apply** posts UUIDs to bulk-override even when rows are outside the newest-3000 table.
- Residual exclude happens **before** top-N rank; Grok ids are UUID-normalized.
- `is_internal_transfer` can be forced on bulk-override (pot-to-pot piles).
- Next Suggest no longer excludes leftover unapplied piles.

## 2026-08-13 — New ET Review: AI clusters + guided assign

- **AI-first:** New `POST /ai/categorize-clusters` asks Grok to pile residual txs (not merchant-key grouping, not `buildSmartGroups`). **No lab heuristic fallback** — requires `AI_ENABLED` + `XAI_API_KEY`.
- Payload: id/date/merchant/short desc/sign/currency/rounded amount/institution; IBANs and long digit strings redacted.
- Review: AI desk + ubiquitous guided assign → similar → rule (row, bulk, cluster apply) + 20s undo.
- Internal-transfer piles set `is_internal_transfer` on apply. Old `/ai/categorize-suggest` unchanged.

## 2026-08-13 — New ET (lab-only Expense tracking fork)

- **Why:** Rework categorization without touching Expense tracking for owner, sandbox, tour, or other tenants.
- **Gate:** `demo_kind === "lab"` (password lab principal, default `LAB_EMAIL=testaccount@o2.pl`). Sandbox/tour/owner do not see nav; `/new-et/*` redirects them to `/expenses/spending`.
- **Copy:** `/new-et/spending` is a UI copy of Spending (same dashboard API). Chart/footer links go to `/new-et/categorize`.
- **Categorize:** Review | Rules | Categories. Full ledger. No Groups/AI/guided similar/undo/latest-import/starter-rules/apply-rules. New: Income only filter, Uncategorized All, Categories CRUD, manual rule create.
- **Ledger:** same APIs and sheet tabs. Old `/expenses/*` unchanged.
- **Spec:** `docs/NEW_ET_SPEC.md`.

---

## 2026-08-13 — Upload / categorize polish (focus, residual similar, prices)

- **Upload:** outcome card collapses stats/SHA under “Import details”; always show filename + status.
- **Prices:** kick `refreshPrices` after investment import; Layout soft tick on wealth mount; PriceStatusBanner shows fetching + ETA estimate.
- **Import categories:** `CategoryEngine` no longer auto-falls back to Other — unmatched stay `category_id=null`.
- **Categorize:** group/AI focus **wins** over filters (empty Groups table fix); similar-review residual-only + A–Z; clear/reset category via restore-assignments; guided similar CTA above Groups/AI panels.

## 2026-08-13 — Categories cleanup must not wipe statement data

- **Bug:** Settings cleanup scope `categories` used `replace_all_rows` on **Transactions** to null `category_id`. On Google Sheets that is **clear + full rewrite**; a failed/partial write (or huge tab) can destroy cash history while the user only asked to delete rules/categories.
- **Fix:** unassign categories via **`upsert_rows` patch only**; never full-replace Transactions for this scope. Post-check asserts Transactions/StatementFiles/investments row counts do not shrink on categories-only cleanup.
- **Copy:** scope description/notes state explicitly that uploads and money history are kept.

## 2026-08-13 — Clean empty-account alerts (lab isolation)

- **Root cause:** prod lab disk ledger had been contaminated with full personal history (~14k txs + lots), so alerts correctly fired on that data — looked like “residual” owner alerts on a “fresh” account.
- **Reset:** `python -m backend.scripts.reset_lab_ledger` wipes `LAB_DATA_DIR/ledger.json` and re-seeds public categories only.
- **Cache:** dashboard/alerts cache keys include principal tag (`demo:lab:…` vs `user:…`) so demos never share owner GET caches.
- **sheets/status:** reports `disk_memory` for lab (not env `SPREADSHEET_ID`).
- **Invariant:** empty public categories + zero txs/lots → zero alerts.

## 2026-08-13 — Lab test account (disk-persistent demo principal)

- **Password login** via `LAB_LOGIN_ENABLED` + `LAB_EMAIL` + `LAB_PASSWORD` (default email `testaccount@o2.pl`). Never commit the password.
- **`demo_kind=lab`**: full write path (not tour RO), empty **public** category pack like a new sandbox, **does not wipe on logout**.
- **Storage**: `DiskBackedSheetsRepository` JSON under `LAB_DATA_DIR` (default `data/lab/ledger.json`) — not Google Sheets; only difference from a real new user for this principal.
- Landing shows password form when lab is enabled; lab email is not advertised in public-config.
- Frontend: lab banner, onboarding path, AI heuristic fallback parity with sandbox.

## 2026-08-12 — Lot inventory repair + import atomic replace

- **Root causes of wrong holdings:**
  1. Ticker FIFO rebuild could leave **stale open lots** if per-row `delete_by_id` partially failed under Sheets quota / interrupted import.
  2. Same-second events sorted by UUID only — a **Sell could process before Buy**, leaving inventory unreduced (or wrong).
- **Import harden:** on ticker rebuild, `replace_all_rows(InvestmentLots)` (atomic tab replace); `delete_by_ids` batch-blanks stale LotAllocations.
- **FIFO sort:** Buy/StakingReward before Sell/Fee within the same timestamp.
- **Repair:** `python -m backend.scripts.rebuild_lots_from_events --collapse-dupes --dry-run` then live; prints open lots vs event net for PLTR/SPCX/COIN/crypto.

## 2026-08-12 — Async statement upload (proxy timeout fix)

- `POST /upload` accepts file, stores bytes, starts in-process background job; returns `job_id` immediately.
- Client polls `GET /upload/jobs/{id}` until done — avoids Railway/proxy `upstream error` on long crypto/stock FIFO+Sheets imports.
- Retry uses the same async pattern; clear non-JSON/proxy error messages retained.
- Upload UI shows “Processing…” after file transfer while the job runs.

## 2026-08-12 — Categorize reliability polish

- **In-mode workbench:** Groups/AI keep the tx table + guided flow without trapping the user in Review; focus clears on done.
- **AI queue:** prune applied merchants; exclude applied keys; pass `date_from`/`date_to`; show-txs no longer forces empty Uncategorized filter.
- **Coverage:** refresh after assign/undo; label clarifies expense-only (income does not move %).
- **Apply rules:** fills **blanks and Other/Uncategorized** (import residual), so starter install can move coverage.
- **Starter pack:** skips personal lifestyle (moto/biz/local haunts); fuel → Fuel (car); sandbox bootstrap uses public ensure.
- **Clean seeds:** Allianz rule removed from public demo + owner minimal seed defaults.
- **Groups:** newest booking_date first; **sandbox hints** map wellness/spa → Fitness, hotel → Going out.

## 2026-08-12 — Categorize workspace redesign (guided flow + AI + groups)

- **Guided assign:** after manual category assign → offer find-similar → filter to similar (same vendor + amount sign) → group-assign with uncheck exclusions → restore filters → plain-English rule offer (exclusion warnings via `ruleExplain`).
- **Undo toast (~20s):** `POST /categories/restore-assignments` restores prior `category_id` / override / internal flag (supports clear-to-null).
- **Modes:** Review | Groups | AI assist | Rules. Tools labels: Install starter rules / Fill blanks from my rules. Grok only in AI assist.
- **AI quality:** leaf-only catalog; never suggest Other (needs_human); default batch 12; hint + exclude_merchant_keys; sandbox unknown → needs_human not Other.
- **AI apply:** Review & apply opens similar-review (no silent full-cluster write).
- **Groups:** large amounts, near-identical, suspected transfers, uncategorized income, stuck Other, recurring, top merchants, fees/ATM (`smartGroups.ts`).
- CategoryEngine / import rules authority unchanged; AI still suggest-only until human confirm.

## 2026-08-12 — Demo accounts start on setup onboarding

- Both sandbox and tour enter → `/onboarding` (reset per-demo localStorage keys).
- Force gate: incomplete demo onboarding cannot browse app (except Settings).
- Tour: educational setup copy + final **reveal** step (“see account in use”) then full synthetic portfolio.
- Sandbox: interactive setup (upload/bootstrap allowed); tour bootstrap stays 403.
- Real-user onboarding key unchanged.

## 2026-08-12 — Tour showcase seed + market value fix

- Tour had open lots but **empty Prices** → `portfolio_snapshot` set `total_market_value` null; soft refresh skipped for `isReadOnly` and middleware blocked `POST /prices/refresh`.
- Seed illustrative `Prices` for AAPL/MSFT/ETH/VTI/NVDA/GOOGL/BTC; allow tour price refresh (memory-only); Layout soft refresh runs again for tour.
- Richer tour: ~150 txs, 7 lots, uncategorized rows, fitness/subs, multi-bank spend, seed version `v5-showcase-prices-mv`.

## 2026-08-12 — Tour empty after redeploy (seed-on-read)

- Root cause: tour ledger is process-local memory; session cookie survives Railway restart while `demo:tour-shared` is empty; seed only ran on `POST /demo/tour`.
- Fix: `get_repository` calls `ensure_tour_seeded()` for `demo_kind=tour` (idempotent re-fill).
- Seed version key `demo_tour_seed_version` forces full reload when content bumps.
- Test: wipe memory without logout → next GET still ≥40 txs.

## 2026-08-12 — Richer sample portfolio tour seed

- Tour ledger: ~100+ synthetic transactions (salary, rent, groceries, dining, transport, subs, USD spend).
- Banks: Demo Bank (Raiffeisen), Demo Wallet CZK/USD (Revolut), Demo Broker (eToro), crypto pot legs.
- Investments: 4 open lots with **real tickers** (AAPL, MSFT partial sell, ETH, VTI) + 5 events for yfinance quotes; 3 statement-file rows.
- Sparse / fake-ticker tours auto-upgrade (`replace_all_rows`). Still no personal residue.

## 2026-08-12 — Public demo data hygiene (no personal residue)

- Sandbox / tour no longer call owner `ensure_default_categories` (which seeded **`CEZARY BIERNAT`** self-education rule).
- New `backend/schema/demo_public.py`: generic category pack (no Motorcycling / My business), synthetic accounts (`****0001/5500`), synthetic tour txs/lots, Digital Assets rule only.
- Tour seed = `seed_public_tour`; import empty-ledger bootstrap uses `seed_minimal(public_demo=True)`.
- `POST /categories/bootstrap-rules` **403** for `is_demo` (owner keyword pack is personal).
- `POST /categories/ensure-defaults` on demo → public pack only.
- Regression: `test_demos_have_no_personal_residue`.

## 2026-08-12 — Dual public demos (sandbox + tour)

- Replace shared password demo as primary path with **two one-click entries**:
  - `POST /api/auth/demo/tour` — synthetic seed (`seed_full_demo`), `demo_kind=tour`, **server read-only** (middleware + WritableUserDep).
  - `POST /api/auth/demo/sandbox` — per-session empty memory ledger, writable; **wiped on logout**.
- Session: `demo_kind`, `read_only` on `/me`; JWT carries `demo_kind`.
- Landing: “Explore sample portfolio” / “Try with your statements” (no email/password).
- Demo banner variants; Upload/Settings cleanup gated for tour; setup wizard suppressed for demos.
- Env: `DEMO_TOUR_ENABLED`, `DEMO_SANDBOX_ENABLED`, `DEMO_SANDBOX_MAX_ACTIVE`. Legacy password demo optional.
- Tests: `test_dual_demo.py` (isolation, wipe, 403, no Google).

## 2026-08-12 — Admin → personal tenant migration tooling

- Goal: real finances on multi-tenant personal principal (bound sheet); keep platform admin + demo for testing.
- `public-config`: `owner_login_enabled` is **false** when `MULTI_TENANT=true` (owner password remains ST-only).
- `POST /api/admin/migrate-env-sheet` — platform admin one-shot bind of env `SPREADSHEET_ID` to self (safe cutover; refuses if already bound differently / conflict).
- Settings **Admin · Legacy sheet**: bind env id to me, or paste URL/id (+ optional target user). Prefer over Provision for legacy data.
- Docs: cutover/rollback in `MULTI_TENANT.md` + deploy notes in `DEPLOY.md`.
- Tests: public-config MT hide owner; migrate-env-sheet bind/idempotent/403/400.

## 2026-08-12 — Auth review remediations (post-lockdown)

- Safe email equality (no `compare_digest` length 500s); password still constant-time.
- `POST /auth/local-dev` → **403** unless `open_auth_permitted`.
- `public-config` no longer exposes `owner_email`.
- Tests: owner login, demo never SA, rate-limit 429, production `open_auth:false`.
- Docs/boot log: closed open-auth is **401**, not 503.

## 2026-08-12 — Landing page + demo password login + admin invites

- Public SPA `/login` landing (USPs + Google + optional demo password form).
- `POST /api/auth/password` with `DEMO_LOGIN_ENABLED` / `DEMO_EMAIL` / `DEMO_PASSWORD` (env; default off).
- Demo principal isolated multi-tenant memory ledger; never `platform_admin`.
- `GET /api/auth/public-config` for landing flags (no secrets).
- Protected routes redirect to `/login`; demo banner in Layout.
- Settings: Admin · Invites UI for `platform_admin` in multi-tenant mode.
- Tests: `test_demo_password_login.py`.

## 2026-08-12 — Multi-tenant remediation (review waves W1–W3)

- Production: refuse weak/default `SECRET_KEY`; force `effective_debug=false`; MT prod requires oauth.
- Unique spreadsheet bind + claim API; **bind is platform-admin only**.
- Cron `jobs/tick`: multi-tenant fan-out (no user session); constant-time cron secret.
- Jobs/list/get tenant-scoped; worker threads set tenant context for cache.
- Health `multi_tenant`; sheets/status returns tenant sheet id.
- SPA: not_invited UX, provision button, hide wizard when MT, setup prompt uses `tenant_ready`.
- Stronger isolation tests (callback, bind 409, cron fan-out, cleanup API, AuthMe fields).

## 2026-08-12 — Multi-tenant foundation (W1–W5)

- Control plane SQLite: users + invites (`backend/tenancy/`).
- Config: `MULTI_TENANT`, `CONTROL_DB_PATH`, `PLATFORM_ADMIN_EMAILS`, `MULTI_TENANT_MEMORY_SHEETS`.
- OAuth invite-only when multi-tenant; uninvited → no session.
- `get_repository` binds **only** user-mapped spreadsheet (no env sheet fallback).
- Tenant-scoped response cache, upload store, import locks.
- APIs: `/api/admin/invites`, `/api/tenant/provision|status|bind`.
- Setup wizard disabled in multi-tenant mode.
- Multi-tenant production never permits open auth (even with `ALLOW_OPEN_AUTH`).
- Isolation tests: `test_tenant_isolation.py`. Docs: `docs/MULTI_TENANT.md`.
- Single-tenant default unchanged.

## 2026-08-12 — New-user path (SPA onboarding)

- SPA `/onboarding`: Welcome (USPs) → Google Sheets (status + link to existing `/setup`) → Upload statements → Rules & categories → Ready.
- Soft incomplete-setup **popup** on Home when sheet not configured and onboarding not dismissed; never hard-gates the app.
- **Preview mode** (`?preview=1` / Settings → Preview): full UI walkthrough; blocks upload, bootstrap, apply-rules, ensure-defaults writes so live connection/ledger stay intact.
- Legacy users with `spreadsheet_configured` auto-migrated to completed (no popup after deploy).
- Settings: New-user setup path, Preview, Sheets wizard only. Home banner points at full path + Sheets-only link.
- Progress: `localStorage` `gauntlet.onboarding.v1` (client-only).

## 2026-08-12 — Sheets onboarding wizard (non-technical)

- Upgraded `/setup` Google Sheets wizard: Sheets-first path (Welcome → Cloud → Key → Sheet → Share → Ledger → App ready → Done).
- Illustrated step cards (SVG) instead of fragile Console screenshots; plain-language copy.
- Deploy/GitHub moved under optional advanced on the ready step.
- React: `setupWizardUrl()` (API :8020), Home banner when `spreadsheet_configured` is false, Settings primary CTA.

## 2026-08-12 — Perf: quiet soft-refresh thrash + cheaper history

- Soft price refresh: skip Sheets write / cache invalidate / client fan-out when marks did not move (`quotes_updated`).
- Chart: multi-day history no longer refetches on soft `prices-updated`; window-performance only on range change.
- History: one Prices read for book meta; day-change from series (no extra 5m book download); no per-ticker yfinance fallback when batch frame exists; short response cache (`phist:`).
- Soft interval 90s.

## 2026-08-12 — 1D chart: honest path + desk book secondary

- Reversed 1D tip-pin (no rewriting last Yahoo bar → no fake cliff).
- API meta: `book_market_value_usd` / `book_price_usd` + `book_vs_path_abs` for UI.
- 1D chrome: label “Chart MV” / “Chart last”; desk book + path Δ under headline; subtitle clarifies Yahoo path vs executive desk book.
- Daily ranges still pin tip to book (unchanged).

## 2026-08-12 — UX polish: chrome, alerts, charts, spending, research

- Header: removed manual **Update prices** button and desktop sticky price bar; soft ~60s refresh remains on Home/Investments.
- Portfolio: executive `total_market_value_usd` is authoritative marked MV; unpriced names called out; holdings Value shows cost fallback distinctly; chart last daily point aligns to Prices-tab book mark.
- HoverPanel: flips above trigger / clamps horizontally when near viewport edges (tax runway on tablet).
- Spending: cash-pulse KPIs moved into category chart header (price-history style); bottom cash hero removed.
- Alerts badge: v3 localStorage by stable id + 7d TTL + level escalate; Mark all seen; body drift no longer rebadges.
- Price history: daily trade markers snap to series day on interior Yahoo gaps; crypto densify fills short holes (≤3d); 7d/1m X-axis shows every day label; FE trade attach nearest prior day.
- Position detail: external research links (Google/Yahoo Finance, X cashtag, CoinGecko/TradingView by asset class).
- Research links fix: stock/ETF Google Finance uses `tbm=fin` search (bare `/quote/TICKER` 404s on GF beta); crypto keeps `TICKER-USD` quote path; CoinGecko majors deep-link coin pages; crypto TradingView uses `TICKERUSD` (not `TICKER-USD`).

## 2026-08-12 — Grok categorize assist (Option A / testing)

- Platform SpaceXAI/xAI via `AI_ENABLED` + `XAI_API_KEY` (server-only).
- `POST /api/ai/categorize-suggest` + `GET /api/ai/status`: merchant-batch suggestions for blank/Other/Uncategorized only; validate category UUIDs; no auto-write.
- Per-principal + global daily token caps (`AI_DAILY_TOKEN_CAP`, `AI_GLOBAL_DAILY_TOKEN_CAP`).
- Payload minimized: merchant label, amount_sign, currency (no account numbers).
- UI: Categorize Tools “Suggest with Grok” + confirm Apply; Settings status card; onboarding rules note.
- Deferred: BYOK, paid entitlements.

## 2026-08-12 — Grok cash statement map (Option B)

- Unknown cash CSV after detect fail: `ai_map_eligible` on upload error.
- `POST /api/ai/map-statement` (preview column map + sample rows; redacted samples).
- `POST /api/ai/import-mapped` → soft parse cash txs → same SHA/dedupe/categorize/transfer path (`parser_key=ai_cash_map`).
- Upload UI: Map with Grok → preview → Import. XLSX/investment formats out of scope.

## 2026-08-12 — Grok on writable sandbox demo

- Sandbox (`demo_kind=sandbox`) gets categorize-suggest + cash map even without `XAI_API_KEY` via `AI_SANDBOX_FALLBACK` heuristics (mode `sandbox_demo`).
- Real Grok still used when platform key is configured.
- Tour remains read-only / AI-blocked. Onboarding sandbox copy + deep links to Categorize/Upload AI.

## 2026-08-12 — Analysis capital flows hero

- Analysis: removed HealthBand; order is buy/sell cashflow → combined living-draw + fees + staking hero → FX chart.

## 2026-08-12 — Spending hero, Categorize latest import, Alerts desk

- Spending: Net/Income/Expenses + pace strip combined into one bottom cash-pulse hero.
- Categorize: default loads txs from latest import batch (`latest_import_batch`, ~15m multi-file window via `source_file_id`); removed suggested rules + merchant queue UI; active rules support Edit + Remove (PATCH/DELETE existing APIs).
- Alerts: DCA level `opportunity` (not warn); page is Spending | Stocks | Crypto hero columns.

## 2026-08-12 — Dashboard takes portfolio desk hero

- Home uses former Holdings hero (MV, wealth KPIs, tax runway) + cash month dial + compact alert counts (Spending / Stocks / Crypto → Alerts).
- Removed dashboard triage list, signals strip, cash insight.
- Holdings page: chart + table/detail only (no bottom hero); tax runway deep-link notes Home.

## 2026-08-12 — Live chart values stay top-right (Portfolio + popout)

- Header values block uses `ml-auto` so Portfolio (extra Stocks/Crypto legs) does not wrap to the left; same layout for embedded and popout.

## 2026-08-12 — Holdings layout: chart first, summary last

- Order: live chart → holdings table + detail → hero (wealth KPIs + tax-free runway embedded).
- Table/detail: no internal vertical scroll; table reserves height for full ticker count so asset filters do not shrink the card.
- Removed DCA teaser from Holdings (DCA page unchanged).

## 2026-08-12 — Live chart + popout density / layout

- Holdings ticker strip: square centered tiles (more per row); % only (price in title).
- Popout: full `100dvh` flex column — chart flex-fills remaining height; strip scrolls if needed.
- Soft “Updating…” sits to the right of MV values with reserved width (no chart vertical jump).

## 2026-08-11 — Home executive redesign (two dials + triage)

- Dashboard: number-first **portfolio MV** + **month net cash** hero; unified Needs attention (alerts + health + uncat); secondary Signals (unrealized %, pace, TTM draw vs safe from snap, tax-free now); cash insight from existing dashboard top domain/merchant.
- Removed from Home: flat 6-tile wealth grid, full tax runway, top-holdings chips, DrawMetricsCard (extra GET), footer quick-link sitemap.
- Safe draw on Home: display-only `min(4%×MV, tax_free_now)` matching backend heuristic — no formula change.

## 2026-08-11 — Investment desk review fixes (sort, tax-free, chart mode)

- **Holdings table:** null ROI metrics always sort last; Tax-free column sorts by free-share % (unlock date tie-break); display honest % (no 99→100, show 0% locked).
- **Chart:** area stroke follows book MV endpoints; portfolio legs use `mv_change_usd` in Book mode; mode chips reflect effective mode + a11y radiogroup; equity strip includes ETF.
- **Reliability:** Holdings load uses generation token; cold errors keep Investments shell; DCA teaser loads once (no prices thrash); deleted dead `PortfolioMvChart.tsx`.

## 2026-08-11 — Investment Desk rework (Holdings + Analysis + DCA + Tax)

- **Holdings** executive desk: hero (grade + MV + price status), nested wealth KPIs, scannable holdings table + detail panel (replaces chip strip), live chart below, tax runway, DCA top-3 teaser.
- **Analysis**: removed duplicate `PortfolioMvChart` (single MV chart home = Holdings); keeps health, draw, cashflow, fees, staking, FX.
- **IA**: four tabs retained (Holdings | Analysis | DCA | Tax); shared `InvestmentsPageShell` + feature-module imports (no page re-exports).
- Domain math / APIs unchanged (snapshot, digests, history, draw, DCA, tax-report). UI presentation + hierarchy only.

## 2026-08-11 — Chart performance clarity (Performance | Book toggle)

- UX only: MV charts default primary **Performance** (`mark_pnl_*`); toggle **Book** for market value Δ (`change_abs` = last−first, matches line).
- Secondary line when they diverge: other metric + **Cash/qty effect** (`net_capital_abs`).
- Ticker charts: **Price change** only (no toggle). Strip: **price move** (not ambiguous “performance”).
- Portfolio legs: Stocks (session) / Crypto (24h) + note legs may not sum to chart on 1D.
- Shared helpers: `lib/chartChangeMode.ts`, `lib/chartChangeHeadline.ts`. Backend math unchanged.

## 2026-08-11 — PR6 hygiene + cache single-flight + light I/O (Wave 3 / P3)

- Deleted remaining OS duplicate `* 2.*` sources (routes/services/frontend/docs); left `__pycache__` alone.
- `response_cache.cached`: per-key single-flight so concurrent misses share one factory; concurrent unit test.
- Offload heavy sync work from the event loop: `asyncio.to_thread` on upload/retry and dashboard/alerts `cached(...)`.
- `parse_decimal`: EU/CZ comma-decimal path (`1.234,56`, `1234,56`) without breaking US `1,234.56`.

## 2026-08-11 — PR5 critical product tests (Wave 2 / P2)

- Tests: internal transfers excluded from dashboard `income_usd`/`expense_usd` + pace; fixed brittle pace assert in `test_dashboard_spend`; response_cache unit tests.

## 2026-08-11 — PR3 import harden (lock + ticker-scoped lot rebuild)

- Process-level `threading.Lock` serializes `ImportPipeline.upload` (wait, do not reject).
- On ERROR/PENDING retry or when touched tickers already have events/lots: rebuild those tickers from all non-allocation events (`lot_rebuild.py`); drop stale LotAllocations/lots; preserve other tickers.
- Ensure Digital Assets Europe category rule before categorize (`ensure_digital_assets_rule`).

## 2026-08-11 — PR1 security: production auth gate + SPA path + deploy-env redaction

- Production + `AUTH_MODE=dev|disabled` without `ALLOW_OPEN_AUTH=true` → unauthenticated routes return **401** (login required). Tests/dev (`APP_ENV=test|development`) still allow open synthetic user.
- Setup wizard: blocked in production when sheet already configured unless `ALLOW_SETUP_WIZARD`; optional `SETUP_TOKEN` / `X-Setup-Token` on write endpoints.
- `GET /setup/api/deploy-env` never returns SA private key (placeholder only + `has_service_account`); template uses `AUTH_MODE=dev` + `ALLOW_OPEN_AUTH=true` for trusted single-user (document prefer oauth).
- SPA fallback path sandbox (`_safe_dist_file`); production CORS never falls back to `*`.

## 2026-08-11 — Chart-first book / mark reconciliation

- Confusion: chart endpoints (+$4.9k book) vs headline mark P&L (+$13.7k) → “missing” $8.8k.
- Cause: mark = q₀×Δp on **open** qty; book = last−first MV (includes sells/capital leaving the book).
  Identity: **Book Δ = Mark P&L + Net capital**. On sells after a rise, mark &gt; book (net capital negative).
- Fix: headline `change_*` = book (matches line); emit `mark_pnl_*` + `net_capital_abs`.
- Portfolio 1D no longer overrides headline with Stocks RTH + Crypto 24h sum (legs stay in `window_components`).
- UI: primary “book”; secondary “Mark P&L · Net capital” when they differ.

## 2026-08-11 — Mark P&L aligned to chart open (no purchase cash)

- Root cause: prior flow method missed USD-less trades; UI big number is MV not P&L.
- Fix: `q0` = qty **entering** chart window; `Σ q0×(p_end−p_start)` on chart first/last bars.
- UI: label Market value vs mark P&L; Book Δ shown when it includes buys/sells.

## 2026-08-11 — Revert trade jump bands / curve colors

- Removed vertical trade bands and colored curve segments; buy/sell △▽ markers remain.
- Kept performance headline (ex-buys/sells).

## 2026-08-11 — Chart performance ex-buys/sells

- Headline `change_*` = ΔMV − buys + sells (price P&amp;L); raw MV Δ kept as `mv_change_*`.
- UI: “performance” label.

## 2026-08-11 — Revolut statement times = Europe/Prague

- Bug: naive Revolut clocks tagged UTC → 1D markers ~2h late in CEST (looked like “just now”).
- Fix: parse naive times in `statement_timezone` (default Europe/Prague); one-shot ledger repair.

## 2026-08-11 — DCA days-since-buy ignores staking rewards

- Bug: open staking-reward lots counted as last buy → zeroed "Xd since buy" for staked coins.
- Fix: `last_buy_dates` uses Buy events + non-staking lots only (BTC unchanged if no rewards).

## 2026-08-11 — 1D holdings by event timestamp

- Bug: 1D MV used date-only qty → same-day buys appeared at UTC midnight (~2am CEST).
- Fix: `HoldingsTimeline.ts_steps` + `qty_as_of_ts`; intraday aggregate uses event instants.

## 2026-08-11 — Trade markers after last Yahoo bar

- Bug: buys after last 5m bar (or today with no daily close) were dropped from the chart.
- Fix: snap those trades onto the last series bar (same day or +1 day lag).

## 2026-08-11 — Trade markers: both sides + multi counts

- Buy = green △ up, sell = red ▽ down; when both on same bar, vertical split.
- Count badge when ≥2 buys or sells on that bar; tooltip summary `N buys · M sells`.

## 2026-08-11 — Fix 1D phantom trade markers

- Bug: day-level trade attach painted every buy/sell on **every** 5m bar of that calendar day.
- Backend: intraday window uses event datetime; markers snap to one series bar timestamp.
- Frontend: exact timestamp match on 1D; daily ranges keep day matching.

## 2026-08-11 — Multi-file statement upload

- Upload page: multi-select / multi-drop; sequential `POST /api/upload` per file (dedupe-safe).
- Per-file results + batch summary; soft fail continues remaining files; max 25 per batch.

## 2026-08-10 — Dashboard realized annualized ROI

- Snapshot: `realized_holding_years` (cost-weighted from LotAllocation `holding_period_days`) + `realized_annualized_pct` (CAGR, min 90d).
- Dashboard Realized (lifetime) shows total % + ann. % · weighted years.

## 2026-08-10 — Portfolio window Δ = Stocks + Crypto components

- Portfolio headline change is **sum of Stocks book Δ + Crypto book Δ** (same windows as those tabs: RTH vs 24h on 1D).
- UI shows Stocks / Crypto legs under the portfolio total.

## 2026-08-10 — Portfolio 1D shared 5m grid (stock/crypto sync)

- Replace ad-hoc seed inject with **uniform 5m UTC grid** over last 24h: every ticker marked every bar (equity prior close overnight, crypto live).
- Removes desync/over-correction between stock and crypto timestamps.

## 2026-08-10 — Fix 1D portfolio low/flat start after prior-close carry

- Bug: equity seed 30s before crypto → first MV was **stocks-only** (~half book), then jump → flat high plateau.
- Fix: shared window-open timestamp for equity prior close + crypto carry-back; `preseed_first_marks` so first bar is full book.

## 2026-08-10 — Fix 1D portfolio vs stocks/crypto window math

- Portfolio 1D was “Last 24h” but series started at stock open (coverage) → Δ excluded overnight crypto.
- Inject equity **prior RTH close** at T−24h so overnight crypto is in portfolio window; Δ ≈ stocks session + crypto 24h.
- Clearer session subtitles (US RTH vs last 24h).

## 2026-08-10 — Annualized open ROI (cost-weighted)

- Digest: `holding_years` (cost-weighted lot age) + `annualized_unrealized_pct` (CAGR cost→MV, min 90d).
- Verify holdings: sort toggle Total vs Annualized; chips + panel show ann. % and weighted years.

## 2026-08-10 — Live chart ticker strip with range performance

- `GET /prices/window-performance?range=` — per open ticker first→last % for chart window.
- Holdings + pop-out: tickers listed under chart with colored range return; click selects series.

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

## 2026-08-11 — Lots + tax: no phantom FX losses, short-sell notes, unique disposals

- C4: sell allocation leaves `realized_gain_usd/czk` None when FX convert fails (no `0 - cost` phantom loss).
- H5: short/over-sell tags sell notes `unallocated_qty=…; short_sell_unallocated`.
- H6: cross-currency fee converts into lot native (or add_n=0); never mixes currencies in `cost_basis_native`.
- C5/M8: tax report uses `iter_unique_allocations` and skips `transfer_out` notes.

