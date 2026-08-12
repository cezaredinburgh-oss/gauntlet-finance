# Gauntlet Finance App — Agent & Engineering Rules

This file is binding for humans and coding agents. Prefer simple, readable code that matches existing patterns. When a rule conflicts with a quick hack, the rule wins.

---

## 1. Stack (do not freestyle)

| Layer | Stack | Notes |
|-------|--------|--------|
| Backend | Python 3.12+, FastAPI, Pydantic v2, uvicorn | Package root: `backend/` |
| Storage | Google Sheets (service account) | Primary ledger. `InMemorySheetsRepository` **only** for tests / `REPO_BACKEND=memory`. Optional **multi-tenant** mode (`MULTI_TENANT=true`): invite-only OAuth + control-plane SQLite mapping each user → own spreadsheet — see `docs/MULTI_TENANT.md`. Default remains single-tenant. |
| Frontend | React 18, TypeScript (strict), Vite, Tailwind, react-router-dom, recharts | Package root: `frontend/` |
| Money / time | `decimal.Decimal`, `backend/common/money.py`, `backend/common/timeutil.py` | Never invent FX; never use float for money |
| Prices / FX | yfinance + CNB FX | Allowed market data; not a portfolio import source |
| Tests | pytest (`backend/tests`), frontend `tsc --noEmit` | See §7 |

**Ports (document any deviation):** API `8020`, UI `5190`.

**Out of scope forever:** importing positions or history from external portfolio apps (only statement files under `Bank statements/` or test fixtures).

---

## 2. Clean architecture (dependency direction)

```
frontend/src  →  HTTP /api/*
backend/api/routes  →  services (+ deps)
services  →  engines, parsers, common, sheets.repository
engines / parsers  →  schema models, common  (no FastAPI, no HTTP)
sheets  →  Google API / InMemory  (no business rules beyond persistence)
```

### Layer responsibilities

| Layer | Path | Owns | Must not |
|-------|------|------|----------|
| Routes | `backend/api/routes/` | Auth deps, query/body validation, HTTP status, thin orchestration | Business formulas, sheet cell math, parser logic |
| Schemas | `backend/api/schemas.py` | Request/response shapes | Domain side effects |
| Services | `backend/services/` | Use-cases: dashboard, import, tax, alerts, cache keys | Raw HTTP details; direct Google client calls when repo exists |
| Engines | `backend/engines/` | Pure-ish domain: categorize, lots, FX, transfer match | I/O, FastAPI |
| Parsers | `backend/parsers/` | Statement → domain rows | Persistence, categorization policy |
| Common | `backend/common/` | Money, time, hashing | App wiring |
| Sheets | `backend/sheets/` | Repository interface + Google/InMemory | Portfolio math |
| Schema models | `backend/schema/` | Tab models, defaults, seeds | API routing |
| UI pages | `frontend/src/pages/` | Route screens, data loading UX | Duplicating domain formulas that belong on the API |
| UI features | `frontend/src/features/` | Cohesive feature modules (e.g. investments) | Global layout chrome |
| UI API | `frontend/src/api/` | Typed client, `ApiError`, DTO types | Business rules that change ledger meaning |

**Rules:**

1. **Routes stay thin.** Parse inputs → call one service (or a small composition) → return. No multi-page sheet loops in route handlers.
2. **Services own use-cases.** One obvious entrypoint per operation (`dashboard_summary`, `build_alerts`, import pipeline steps).
3. **Engines/parsers are framework-free.** No `fastapi`, no `Request`, no env reads buried mid-formula.
4. **Repository is the only write path** to ledger tabs. Do not open ad-hoc Sheets clients from services.
5. **Frontend does not re-implement tax/lot/FIFO math.** Display API results; client-side code may format, filter, and chart—not redefine cost basis.
6. **No circular imports** across layers. If A needs B and B needs A, extract a pure helper to `common/` or `engines/`.
7. **New code goes in the correct layer** even if a nearby file already violates this. Do not grow god-modules; split when a file’s responsibility is unclear from its name.

### Domain pipeline (import)

```
upload → SHA-256 idempotency → detect parser → parse → dedupe
  → categorize → internal transfer match → FIFO lots → persist
```

Do not skip stages or persist partial investment state without an explicit repair/bootstrap script path.

---

## 3. Domain non-negotiables

These override convenience:

1. **Statements-only ledger** — `Bank statements/` or fixtures. No desk/portfolio app imports.
2. **Google Sheets primary store** — service account. InMemory only for tests / explicit memory backend.
3. **`Decimal` for all money** — never `float` for amounts, qty, fees, FX rates used in calc. Convert at the boundary once; stay in `Decimal` until serialization.
4. **Internal transfers** — set `is_internal_transfer = true`; they must **not** affect income/expense totals.
5. **Revolut crypto Buys** — `qty_net = qty_gross * (1 - fees/value)` (fee-net quantity).
6. **Digital Assets Europe cash legs** → internal + Crypto funding category (not spending income/expense).
7. **Czech 3-year exemption** — default **1095 days** tracked on open lots.
8. **Transaction amounts** — statement-native amount + currency; historical secondary currency only when stored. **Never invent FX.** Dashboard / spend totals: **USD**.
9. **Display** — USD primary, CZK secondary (hover/tooltip). Dark Desk-like glass theme. Home = executive summary.
10. **Stable category IDs** — UUIDs; do not renumber by name.
11. **Repair/bootstrap scripts** — support `--dry-run` when they mutate data.
12. **Formula uncertainty** — read Collective reference first, improve deliberately, record deviation in `docs/BUILD_LOG.md`.

---

## 4. Language standards

### 4.1 Python

- `from __future__ import annotations` in new modules.
- Type-annotate public functions (params + return). Prefer `Decimal`, `date`, `datetime`, `Literal`, and domain models over bare `dict` at service boundaries when a model exists.
- Use `pathlib.Path` for filesystem paths.
- No bare `except:` — catch specific exceptions or `Exception` only at the outer logging boundary.
- Prefer explicit failure (`ValueError`, `KeyError`, domain errors) over silent `None` for programmer mistakes.
- Pydantic models for external JSON shapes; do not hand-roll half-validated dicts for API responses when a schema exists.
- Avoid mutable default arguments.
- Logging: module `logger = logging.getLogger(__name__)`; log failures with context (path, tab, ticker)—never secrets or full service-account JSON.

### 4.2 TypeScript / React

- **Strict mode is mandatory** (`strict`, `noUnusedLocals`, `noUnusedParameters`). Do not weaken `tsconfig` to land a change.
- No `any` unless bridging a truly untyped third-party edge; prefer `unknown` + narrow. Justify every `as` cast.
- Shared API types live in `frontend/src/api/types.ts`; client methods in `client.ts`. Keep them in sync with backend responses when you change contracts.
- Use the shared `api` client and `ApiError` — do not scatter raw `fetch` with inconsistent error handling.
- Functional components only. Hooks at top level. No class components.
- **State:** local UI state in the component; auth in `AuthContext`; server data loaded explicitly (no silent global cache without invalidation).
- **Styling:** Tailwind + existing glass/desk patterns (`cn` helper). No new CSS framework. Match dark theme tokens already in use.
- **Money in UI:** format via existing helpers (`lib/money`, `<Money />`) — do not invent ad-hoc `toFixed(2)` for ledger-critical figures without checking existing components.
- Path alias `@/*` → `src/*` when it improves clarity; stay consistent within a folder.

### 4.3 Naming & files

- Python: `snake_case` modules/functions, `PascalCase` classes.
- TS: `PascalCase` components/types, `camelCase` functions/vars.
- Do not create duplicate files like `foo 2.py` / `Foo 2.tsx`. Remove or never commit OS duplicate copies.
- One primary export purpose per file when practical.

---

## 5. Error handling (consistent)

### Backend

| Zone | Pattern |
|------|---------|
| Auth / permissions | `HTTPException` 401/403 via deps |
| Bad client input | `HTTPException` 400/422 (validation) with clear `detail` |
| Missing resource | `HTTPException` 404 |
| Domain/parse failures | Raise `ValueError` / typed errors in engines/parsers; map to HTTP in routes/services at the edge |
| Infrastructure (Sheets down) | Log + 503 or structured error; do not pretend success |
| Unhandled | Global handler returns 500; **no stack traces or internal paths in production** (`debug` only) |

**Rules:**

1. Error `detail` strings must be safe to show in the UI (no tokens, no file contents, no SA emails required for diagnosis in prod messages).
2. Do not swallow exceptions with bare `pass` unless the no-op is intentional and commented (e.g. optional cache).
3. Partial batch operations (e.g. multi-file upload): soft-fail per item, continue, return per-item results — never silent total success on partial failure.
4. Idempotent imports: duplicate SHA must not create double lots/transactions.

### Frontend

1. Catch `ApiError`; surface `error.detail` to the user.
2. Distinguish network/5xx vs 401 (re-auth / login) vs 4xx validation.
3. Loading and error states are first-class — no blank screens on failure.
4. Do not `console.log` PII or full transaction dumps in production paths.

---

## 6. Performance rules

### Backend / Sheets (critical)

Google Sheets is high-latency and quota-limited. Treat every read/write as expensive.

1. **No N+1 sheet access.** Never read/write one row per loop iteration when a batch/tab read exists. Load tab → process in memory → write back in bulk.
2. **Minimize round-trips** in a single request. Prefer one read of needed tabs over chatter.
3. **Use response caching** (`backend/services/response_cache.py` / existing TTLs) for expensive GETs (dashboard, alerts, heavy investment windows). **Invalidate** on mutations (upload, categorize apply, price refresh, cleanup).
4. **Do not recompute full portfolio history** on every minor UI toggle if a cached window key already covers it — extend cache keys carefully (include params that affect results).
5. **Pagination / filters** for large transaction lists — do not dump unbounded arrays to the client without an existing pattern that already does so intentionally.
6. **CPU-heavy pure work** stays in engines with clear inputs; avoid repeated full-ledger scans inside inner loops (index by id/ticker/date first).

### Frontend

1. **No unnecessary re-renders:**
   - Stable callbacks (`useCallback`) when passed to memoized children or effect deps.
   - `useMemo` for expensive derived charts/aggregations, not for trivial primitives.
   - Context values memoized (`useMemo` on provider value).
2. **Effects:** every `useEffect` has complete deps; no “run always” data thrash. Guard fetches with abort or ignore-stale flags when timeframe changes quickly.
3. **Do not fetch the entire app on one page mount** if existing endpoints are split — use the endpoint that matches the view.
4. **Charts:** avoid rebuilding series objects every render; keep marker math in helpers (`lib/chartTrades` etc.).
5. **Lists:** key by stable ids, not array index, when order can change.

### General

- Measure before micro-optimizing pure Python/TS that is not on a hot path.
- Hot paths: dashboard summary, holdings timeline, price history, categorize list, import pipeline.

---

## 7. Testing expectations

### Minimum bar for a change

| Change type | Required tests |
|-------------|----------------|
| Parser / detect | Fixture-based parse test; edge rows (fees, empty, multi-currency) |
| Engine (lots, transfers, categorize, FX) | Unit tests with InMemory repo or pure fixtures |
| Service / API behaviour | API or service test proving income/expense exclusion, totals, or contract |
| Tax / exemption / fee-net crypto | Explicit numeric assertions with `Decimal` |
| Bug fix | Regression test that fails before the fix |
| Frontend-only presentation | `npm run lint` (tsc) must pass; add logic tests only if pure helpers change |

### Rules

1. **Default storage in tests:** InMemory — never hit real Google Sheets or live yfinance in unit tests unless a test is explicitly marked/optional integration.
2. **Fixtures** live under `backend/tests/fixtures/` or synthetic rows in-test. Do not commit real personal full statement dumps into tests.
3. **Assert money with `Decimal`**, not floats. Compare quantized values when serialization rounds.
4. **Internal transfer tests** must prove non-impact on income/expense.
5. Run **`pytest`** for backend before claiming done. Run **`npm run lint` / `npm run build`** when UI or shared types change.
6. Do not delete or skip tests to “go green” without replacing coverage and noting why in `docs/BUILD_LOG.md`.
7. Prefer focused tests over one mega-test that asserts the entire app.

### Coverage intent (practical, not cargo-cult)

- Aim for **high coverage on engines, parsers, money/time, transfer match, lots, tax math**.
- Routes may be thinner if services are well tested.
- UI: typecheck is the gate; pure `lib/*` helpers deserve unit tests when non-trivial.

---

## 8. Security basics

1. **Never commit secrets:** `.env`, service account JSON, session keys, `Google API key/`, `secrets/`. Use `.env.example` and docs only.
2. **Auth:** respect `auth_mode`; production must not ship with open write access. Session cookie + credentials patterns already in `deps` / auth routes — do not bypass `UserDep` on mutating routes.
3. **CORS:** configure explicit origins in non-dev settings; do not “fix” prod CORS with permanent `*`.
4. **Uploads:** treat files as untrusted; size limits and parser detect already exist — do not execute file content; parse only.
5. **Injection:** no dynamic SQL (N/A); still sanitize anything reflected into HTML. React escapes by default — avoid `dangerouslySetInnerHTML` unless unavoidable and sanitized.
6. **Logs:** no passwords, cookies, or full bearer tokens. Redact service account fields.
7. **Dependencies:** prefer pinned ranges already in `requirements.txt` / lockfile; do not add heavy deps for one-liners.
8. **Admin/repair scripts:** dry-run first; do not expose destructive scripts as unauthenticated public routes.

---

## 9. API & contract conventions

1. Domain API under **`/api/*`**. Health: `/health` and `/api/health`.
2. Auth-required routes use `UserDep` (or document public exception).
3. JSON money fields: strings or number-safe serialized decimals consistent with existing schemas — **do not introduce float drift** in new fields.
4. Breaking response shape changes require updating `frontend/src/api/types.ts` and all callers in the same change set.
5. Prefer query params for filters; POST bodies for mutations and long payloads.
6. Cache-sensitive GETs: document TTL and invalidation triggers in code comments when non-obvious.

---

## 10. Frontend product conventions

1. **Theme:** dark Desk-like glass. Do not introduce a light-theme-only component.
2. **Home (`/`):** executive summary — wealth + cash insight, not a raw spreadsheet dump.
3. **Spending** lives on spending routes; do not overload Home with full categorize UX.
4. **Price refresh:** Layout control → POST refresh → invalidate → `prices-updated` (or existing event) → dependent views refetch.
5. **Investments:** verify holdings before trusting fancy KPIs; analysis/DCA are separate routes.
6. Reuse `Layout`, `TimeframePicker`, `Money`, chart helpers — do not fork parallel widget systems.

---

## 11. Process (Gauntlet Loop)

1. **Design first** for non-trivial work (`docs/GAUNTLET_DESIGN.md` + adversarial review to zero open issues when operating at design scale).
2. **PR-sized slices** — one coherent behavior per change set.
3. **Implement → tests → verify → self-review → `docs/BUILD_LOG.md` entry.**
4. Self-review checklist before “done”:
   - [ ] Statements-only preserved  
   - [ ] Internal/crypto-pot moves do not double-count as spend  
   - [ ] Fee-net crypto correct if touched  
   - [ ] Caches invalidated on write paths  
   - [ ] `Decimal` / types correct  
   - [ ] No secrets committed  
   - [ ] Layering respected (no business logic dumped in routes/UI)  
5. Simple readable code over cleverness. No speculative abstractions.

---

## 12. Commands

```bash
# Backend tests (repo root)
pytest

# Frontend typecheck / build
cd frontend && npm run lint
cd frontend && npm run build

# API (dev)
uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8020

# UI (dev)
cd frontend && npm run dev
```

Windows: `Start-App.ps1` / `Start-App.bat` for local bring-up.

---

## 13. Definition of done (agent checklist)

A task is not done when code merely “looks right.” It is done when:

1. Behavior matches domain non-negotiables (§3).  
2. Code sits in the correct layer (§2).  
3. Errors are handled consistently (§5).  
4. No new N+1 sheet patterns or render thrash (§6).  
5. Tests/typecheck required by §7 pass.  
6. Security checklist in §8 holds.  
7. BUILD_LOG updated if formulas or import semantics changed.  
8. No debug leftovers, duplicate `* 2.*` files, or commented-out dead blocks left as the real fix.

If unsure: **match existing module patterns**, then tighten toward these rules—never loosen money, transfer, or tax correctness for convenience.
