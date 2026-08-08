You are building Gauntlet Finance App — a complete, runnable personal multi-currency finance application.

### Absolute paths (strict)
- Write only inside: C:\Users\cezar\iCloudDrive\Gauntlet Finance App
- Reference implementation (read-only, never modify): C:\Users\cezar\iCloudDrive\Collective personal finance app
- Rebuild blueprint (read first): C:\Users\cezar\iCloudDrive\Gauntlet Finance App\docs\SOURCE_SYSTEM_REBUILD_BLUEPRINT.md
- Example bank statements: C:\Users\cezar\iCloudDrive\Gauntlet Finance App\Bank statements

If the blueprint is missing, reconstruct requirements from Collective’s README.md, backend/README.md, docs/superpowers/specs/*, and core modules under backend/ + frontend/src/.

### The bar (non-negotiable)
The finished product must beat these real references on the dimensions that matter:
- Monzo → clarity, mobile-first transaction experience, speed of insight
- Sharesight → lot-level investment tracking + tax reporting depth
- Linear → clean, fast, data-dense interface
- Collective Finance (the reference app above) → exact domain behaviour (statements-only ledger, Czech FX/tax rules, Revolut fee-net crypto, internal transfers, executive + spending + investments)

You must compare against the real references (and the Collective source) directly, not against a description of them. The builder never grades its own work.

### Product owner constraints (non-negotiable)
1. Statements-only ledger from Bank statements/ (or fixtures). No external desk/portfolio imports. yfinance prices + CNB FX allowed.
2. Multi-currency: CZK, USD, EUR, PLN minimum. Display USD primary, CZK secondary (hover/tooltip).
3. Czech 3-year securities tax exemption (default 1095 days) tracked on open lots.
4. Institutions: Raiffeisen cash, Revolut cash + stocks + crypto, eToro.
5. Internal transfers must never count as income/expense (is_internal_transfer = true).
6. Revolut crypto fee-net on Buys: qty_net = qty_gross * (1 - fees/value).
7. Digital Assets Europe cash legs = crypto pot funding / sell proceeds → treat as internal + Crypto funding category.
8. Categories must include Fitness (under Health) and My business (3D-print motorcycle parts): materials/filament, tools, shipping, biz other + business income.
9. UI: dark Desk-like glass theme. Home = executive summary (wealth + cash). Spending detail on its own page.
10. Prefer API port 8020, UI port 5190 (document if different).

### Required architecture
Gauntlet Finance App/
  backend/          # FastAPI, parsers, engines, services, sheets repo, scripts, tests
  frontend/         # React + Vite
  docs/             # design outputs + BUILD_LOG
  Bank statements/  # fixtures or symlink
  secrets/          # gitignored service account
  .env.example
  README.md
  Start-App.bat / Start-App.ps1

Storage: Google Sheets (service account) as primary ledger + InMemory repo for tests.
Tabs: Accounts, Transactions, InvestmentLots, InvestmentEvents, Categories, CategoryRules, FXRates, StatementFiles, Settings, Prices.

Pipeline: upload → SHA-256 idempotency → detect parser → parse → dedupe → categorize → internal transfer match → FIFO lots → persist.

Key services: dashboard-summary, alerts (with categorize drill-down URLs), investments snapshot, ticker digests, prices refresh, tax report JSON, categorization bootstrap/merchant queue.

Frontend routes (exact behaviour expected):
- / → Executive snapshot (portfolio health + wealth KPIs + cash month steppers + alert strip)
- /expenses/spending → timeframe → category chart → net/income/expense → 30d pace
- /expenses/categorize → tx table, rules, merchant queue, URL filters + sticky banner
- /expenses/alerts → alerts with working drill-downs
- /investments → verify holdings first, then KPIs + tax runway
- /investments/analysis → health, buy vs sell cash (cumulative reinvest %), fees, staking
- /upload
- /settings

Price refresh: Layout button → POST refresh → invalidate cache → dispatch prices-updated → Executive + Holdings refetch.

### Mandatory Gauntlet Loop process

You will not vibe-code the whole app in one unstructured pass.

#### Phase 0 — Design gauntlet
1. Writer mode: produce docs/GAUNTLET_DESIGN.md covering Goals/non-goals, Architecture (Mermaid), Data model, Import pipeline, Portfolio formulas, API surface, Frontend IA, Key Decisions + Alternatives, Risks, Ordered PR Plan.
2. Reviewer mode (fresh context, adversarial): produce docs/GAUNTLET_DESIGN_REVIEW.md with structured issues:
   ### Issue N: title
   - Severity: critical | major | minor | nit
   - Section: ...
   - Description: ...
   - Suggestion: ...
   - Status: open
   Verify every claim against the Collective source code.
3. Revise until the review file shows zero open issues. Writer may mark wontfix with justification; if the same dispute is re-opened twice, escalate to docs/OPEN_QUESTIONS.md and choose a documented default.

Exit Phase 0 only when review shows 0 open issues.

#### Phases 1–N — Implementation gauntlets
For each PR in the design’s Ordered PR Plan:
1. Implement only that PR’s scope.
2. Write/update tests for the slice.
3. Run verification (pytest backend; tsc/build frontend when UI lands).
4. Self-review checklist: statements-only preserved, no double-count on internal/crypto-pot moves, fee-net crypto correct, cache invalidated, Decimal/types correct.
5. Append a short entry to docs/BUILD_LOG.md.
6. Only then start the next PR.

If a phase creates a design conflict, run a mini write→review loop on GAUNTLET_DESIGN.md before continuing.

Continuous rules:
- Simple, readable code over cleverness.
- Decimal for all money; stable UUID category ids.
- Repair/bootstrap scripts support --dry-run.
- Never commit secrets or real .env.
- When unsure of a formula, read Collective first, then improve and note the deviation in BUILD_LOG.

### Definition of Done (v1)
- README.md explains setup (Sheets service account, ports, Start-App).
- Upload of Raiffeisen + Revolut expenses + Revolut crypto + stocks + eToro works (fixtures sufficient).
- Idempotent re-upload.
- Executive dashboard loads wealth + cash; month steppers work.
- Spending page order: timeframe → category → KPIs → pace.
- Categorize + merchant queue + rules.
- Alerts open filtered categorize views.
- Investments: verify holdings, tax runway, analysis cashflow with stable reinvest curve.
- Price refresh updates executive MV/unrealized without full page reload.
- Default categories include Fitness + My business.
- Digital Assets Europe treated as internal crypto pot.
- pytest green for core domain; frontend typecheck clean.
- docs/GAUNTLET_DESIGN.md + final review with 0 open issues + docs/BUILD_LOG.md.

### First actions (do these now)
1. Read the blueprint fully.
2. Skim Collective: backend/schema/models.py, engines/lots.py, parsers/revolut_crypto.py, services/import_pipeline.py, services/statement_extras.py, frontend/src/App.tsx.
3. Start Phase 0 design gauntlet (design doc + adversarial review to zero open issues).
4. Then implement PR1 scaffold.

Do not wait for confirmation between PR phases unless blocked by an open product question. Record defaults in OPEN_QUESTIONS.md and proceed.