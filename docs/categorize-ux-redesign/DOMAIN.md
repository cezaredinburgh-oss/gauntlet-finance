# Categorize UX redesign — domain (ledger facts)

This document explains **what categorization means in the Gauntlet ledger** so a hub + drill-in + filtered-tx + full-row-detail design can reuse existing formulas. It does **not** specify UI.

Binding sources: `Agents.md` §3; `docs/CATEGORIZE_FLOW.md` (approved 2026-08-14); `docs/expenses-ux-research/DOMAIN.md`; `backend/engines/{categorize,core_pack,transfer_match}.py`; `backend/services/{categorization,import_pipeline,ai_categorize,vendor_memory,dashboard}.py`; `backend/schema/{models,default_categories,ensure_defaults}.py`; `backend/api/routes/{transactions,categories,ai}.py`; `frontend/src/{api/types.ts,lib/ruleSuggest.ts,features/categorize-next/txView.ts}`.

Money: statement-native `amount` + `currency`; stored `amount_usd` / `amount_czk` when present; **never invent FX**. Internals (`is_internal_transfer = true`) **do not** enter income/expense. Category IDs are **UUIDs**.

---

## 1. Categorized vs uncategorized vs suggested vs rule-matched

These are **not** four mutually exclusive sheet columns. A row has one `category_id` (nullable UUID), one `category_override` bool, optional `suggest_*` tags, and an internal-transfer flag that is independent of category.

### 1.1 Ledger assignment (`category_id`)

| State on the row | Meaning |
|------------------|---------|
| `category_id is None` | Blank. Import is supposed to leave new cash rows here. |
| `category_id` = a real leaf (Groceries, Salary, …) | Assigned. May or may not be locked (`category_override`). |
| `category_id` = Other (`…000140`) or Uncategorized (`…000141`) | **Residual**, not coverage. Same as blank for “work left.” |
| `category_id` unknown / archived | Treated as residual by coverage helpers. |

Stable IDs:

```26:92:backend/schema/default_categories.py
CAT_INCOME = _id(1)
...
CAT_INTERNAL = _id(111)
CAT_CRYPTO_FUND = _id(122)
CAT_OTHER = _id(140)
CAT_UNCATEGORIZED = _id(141)
```

### 1.2 Residual / “uncategorized” (product, not a UUID)

Coverage and Review treat a row as **still to categorize** when `_is_blank_or_other_category` is true:

```
category_id is None
OR category missing from the map
OR category.id in {CAT_OTHER, CAT_UNCATEGORIZED}
OR name.strip().lower() in {"other", "uncategorized"}
```

**Stop:** `life_domain == Other` is **not** residual. A user-created **Travel** / **Gifts** / **Pets** with `life_domain=Other` is a real assignment (lab Travel `…cfec61` leaves leftover without rewriting `category_id`). Catch-alls remain residual by **stable UUID** and name, so a renamed default Other or a user-created extra “Uncategorized” still counts as work left.

Frontend `isResidualCategory` / next `txHasRealCategory` match that. Grok+ `is_blank_category` is the same leftover IDs **plus** it skips `category_override` — do not collapse the two.

**Ledger coverage counts** (`GET /categories/coverage`): skip archived **and internals**, then split residual vs real:

```315:333:backend/services/categorization.py
# tx_categorized / tx_uncategorized / tx_total — full ledger, excl. internals
```

**Expense USD coverage** (same endpoint, last N days): expenses only (`amount < 0` after USD sign), skip internals/archived; residual via the shared leftover predicate (not `life_domain == Other`). Amber 70%, target 90%. `progress_note`: `Target 90% expense coverage (blank / Other / Uncategorized catch-alls count as leftover).` Travel-as-Other spend can jump coverage % without tx writes; `by_domain["Other"]` may still show that spend until Travel is remapped to Entertainment.

**Dashboard spend “uncategorized”** and alerts `uncategorized_high`: same leftover predicate. Internals never enter this math. Dashboard `by_domain["Other"]` can include Travel-as-Other while `uncategorized_expense_usd` does not.

The UI filter token `uncategorized` is **not** the UUID `CAT_UNCATEGORIZED`. It means residual (client-side). Spending bars may use id `"uncategorized"` for that residual rollup.

**Create-UX:** Categories next + inline create require an explicit domain (no silent Other). `/^travel$/i` name hint → Entertainment. No server rewrite of `life_domain` on `create_category`. Classic Categorize is unmounted and unpatched.

**Side effects of the leftover definition:**

1. Recategorizing a Travel-as-Other row (bulk-override / override) **sets `category_override=True`**. First assign from blank / `CAT_OTHER` still does not lock.
2. `apply_rules_fill_blanks` **skips** those rows (`skipped_already`); a later Fuel rule does not steal them.
3. Coverage % can jump without tx writes (see above).

### 1.3 Suggested (tags, not assignments)

Import **never writes `category_id`**. Core pack writes **hints** only:

```124:142:backend/engines/core_pack.py
def tag_transaction(tx, categories):
    """Apply core-pack tag. Never sets category_id."""
    ...
    updates = {
        "suggest_category_id": hit.category_id,
        "suggest_source": "core",
        "suggest_reason": hit.reason,
    }
    if hit.set_internal: updates["is_internal_transfer"] = True
```

| Field | Role |
|-------|------|
| `suggest_category_id` | Proposed category UUID |
| `suggest_source` | e.g. `"core"` |
| `suggest_reason` | Human-readable tag (“ATM / cash withdrawal”, “Digital Assets Europe cash leg”) |

Grok+ / merchant-queue / rule-suggestions **do not persist** onto `suggest_*`. They return JSON for the session. A tagged row is still **uncategorized** until a human (or apply-rules / apply-match) writes `category_id`.

Wipe assignments **keeps tags and internal flags**, clears `category_id` + `category_override`:

```103:124:backend/services/vendor_memory.py
# "Clear user category assigns and memory. Keep tags and internal flags."
```

### 1.4 Rule-matched

`CategoryEngine` / `apply_category_rules`: first **active, non-archived** rule by `(priority, id)` that matches; **skipped entirely** if `category_override` is True.

```69:96:backend/engines/categorize.py
# category_override → unchanged
# ordered by (priority, str(id)); first match wins
# optional rule.set_internal_transfer → is_internal_transfer = True
# fallback_category_id only if caller passes it; import does not
```

**Import does not run this engine.** Rules fire later via `POST /categories/apply-rules`, `POST /categories/apply-match`, bootstrap `also_apply`, merchant-queue apply, or `POST /categories/ensure-defaults` (which fill-blanks after ensuring the tree).

A rule-matched row typically has `category_override=False` so a later rule pass can still move residuals / fill blanks.

### 1.5 Override vs first assign

Human assign does **not** always lock the row:

```411:415:backend/api/routes/categories.py
recategorized = tx.category_override or not _is_blank_or_other_category(tx, cats)
updates["category_override"] = recategorized
```

- First assign **from residual** (blank / catch-all Other & Uncategorized) → `category_override=False` (rules may still retarget).
- Assign when already on a real category (including a named Travel-as-Other leaf), or already overridden → lock (`True`).
- Engine helper `apply_manual_override` always sets override True; **routes do not use it**.

`category_override=True` always wins over rules (`engines/categorize.py`).

---

## 2. Review inbox: vendor buckets and apply

### Why buckets exist

Uncategorized **work is merchant-shaped**, not one-row-at-a-time. Same merchant string (or truncated description) repeats. Review therefore groups residual txs in the **currently loaded page** by vendor key:

```16:25:frontend/src/lib/ruleSuggest.ts
# merchant present → m:{normalized lower}
# else description → d:{first 48 chars lower}
```

Server merchant-queue (`GET /categories/merchant-queue`) does the same grouping on **180d uncategorized expenses** (USD), ranked by spend, with a cheap affinity suggestion. Prefer merchant, else counterparty, else description / original_description (`_uncat_match_key`).

Buckets exist so one decision (“this is Groceries”) can cover N statement rows without teaching a regex first.

Vendor buckets on Review are **client-side from `GET /transactions` items** (default newest 3000). Grok+ / queue ids that fall outside that window are fetched with `GET /transactions?tx_ids=&ids=`.

### How apply works (one tx vs vendor vs rule)

| Intent | Call | Scope | Override flag | Also creates rule? |
|--------|------|-------|---------------|--------------------|
| One row | `POST /categories/{id}/override` `{transaction_id}` | That UUID | Residual → false; else true | No. Records VendorMemory. |
| Many selected / vendor / Grok+ Approve | `POST /categories/bulk-override` `{category_id, transaction_ids[], is_internal_transfer?}` | Deduped IDs; skip archived/missing | Same residual rule | Optional **separate** `POST /category-rules` |
| Merchant-queue apply | `POST /categories/merchant-queue/apply` | **Entire ledger** via `apply_match_to_all_transactions` (`contains`) | `mark_override=False` | Default `create_rule=True` |
| Pattern vs whole sheet | `POST /categories/apply-match` | **Entire ledger**, not the UI filter | Default `mark_override=True` | No (rule is separate) |
| Re-run saved rules | `POST /categories/apply-rules` | Residuals only (`fill_blanks` + Other) | Never | No |

Vendor apply on Review uses **bulk-override of the bucket’s ids**, not apply-match. Optional “make rule” is `createCategoryRule` from a draft of those seeds (`createVendorRule`). Creating the rule **does not** retro-scan the rest of the ledger unless the user also apply-rules / apply-match.

Undo: `POST /categories/restore-assignments` restores prior `category_id` / `category_override` / optional `is_internal_transfer`. Does not reverse VendorMemory increments.

Internal category: assigning `CAT_INTERNAL` (or `is_transfer` + name contains `internal` and not `external`) **sets `is_internal_transfer=True`**. Bulk may also pass `is_internal_transfer: true`.

Assigning **upserts VendorMemory** (`vendor_key` → `category_id`, `assign_count++`). If the row had a `suggest_category_id` **different** from the chosen category, `reject_count++`.

---

## 3. Rules

### Match fields and types

Sheet tab `CategoryRules` (`backend/schema/models.py`):

| Column | Values |
|--------|--------|
| `priority` | Lower number wins; ties broken by `str(id)` |
| `match_field` | `merchant`, `description`, `original_description`, `counterparty_name`, `source_institution` |
| `match_type` | `exact` (case-insensitive), `exact_case`, `contains`, `starts_with`, `regex` (IGNORECASE; invalid regex → no match) |
| `match_value` | Needle |
| `category_id` | UUID |
| `set_internal_transfer` | If true on hit, set the flag |
| `institution_scope` | Optional; compared case-insensitive to `tx.source_institution` |
| `is_active` / `archived` | Inactive or archived rules never match |
| `notes` | e.g. `bootstrap:…`, `merchant-queue:…`, `Created from New ET guided flow` |

Delete rule = **deactivate** (`is_active=False`), not hard-delete.

### Apply-on-import vs retro

**On import (current code):** rules do **not** run. Pipeline is tag + transfer-match + persist.

```561:575:backend/services/import_pipeline.py
# Tag only — never write category_id. Structural hits may flag internal.
tagged_new, n_tagged, n_flagged = tag_transactions(...)
match_result = match_internal_transfers(combined)
```

**Retro / user-triggered:**

| Endpoint | Behavior |
|----------|----------|
| `POST /categories/apply-rules` | `apply_rules_fill_blanks`: only residual rows; never overrides; never **clears** a real category when no rule matches |
| `apply_rules_reclassify_non_override` | Exists in service; re-applies to every non-override row; **not** wired as a dedicated public route |
| `POST /categories/apply-match` | One synthetic rule vs **all** txs. Modes: `fill_blanks` \| `reclassify_non_override` (default) \| `force` (includes overrides) |
| `POST /categories/bootstrap-rules` | Install generic keyword pack (personal lifestyle needles skipped); `also_apply` default **True** → fill-blanks |
| `POST /categories/ensure-defaults` | Upsert tree + Digital Assets rule, then fill-blanks |
| Creating a rule in Rules mode | Persist only. **Does not** apply to historical rows |

Default new-rule priority in UI is `100`. Bootstrap keywords use priorities 5–45 (internals / salary / DA at the tight end). Merchant-queue rules use priority `40`.

### Precedence vs Grok+

1. `category_override=True` — frozen vs rules.
2. Active `CategoryRules` by priority — only when a fill/reclassify/import-style apply runs.
3. VendorMemory (`assign_count >= 2`) — **Grok+ suggestion only**, not a ledger write.
4. Core-pack `suggest_*` — **Grok+ suggestion only** (plus Review “Tag:” line).
5. Cheap preclassify, then leftover Grok JSON — **suggest-only**.

Grok never outranks a saved rule on the sheet, because it does not write the sheet. If the user Approves a Grok guess, that is bulk-override (human), then memory/rules as above.

---

## 4. Grok+ (suggest-only)

All `POST /api/ai/*` categorize paths **do not write** `category_id` and **do not** invalidate dashboard cache.

| Endpoint | Role |
|----------|------|
| `POST /ai/vendor-suggest-plus` | Grok+: residual vendors, **12 / batch**, UI loops. Date window **ignored** in the route (`date_from/to=""`). `plus=True`. |
| `POST /ai/vendor-suggest` | Named merchants, cap 10, `web_search=True` (prompt still says knowledge-only). |
| `POST /ai/categorize-suggest` | Fallback generic suggest. |
| `POST /ai/categorize-clusters` / `categorize-presets` / `categorize-ask` | Residual “piles”; still suggest-only. |

Plus pipeline (`ai_categorize.suggest_categories`, `plus=True`):

1. Cluster **blank/residual** txs (override rows excluded). Internals excluded for plus.
2. **VendorMemory** if `assign_count >= 2` → suggestion confidence 0.97, reason “Learned from N assigns”.
3. Else **core tag** on any tx in the cluster (`suggest_category_id`) → confidence 0.9, reason from `suggest_reason`.
4. Else `vendor_preclassify`.
5. Leftover **searchable** merchants → Grok leftover prompt (max 12). Bank-narrative leftovers → `needs_human=true`, no category.
6. Validated against **leaf** catalog UUIDs. Other/Uncategorized **blocked**. Confidence floor 0.55 or `needs_human`.

Payload minimization: merchant label, amount **sign**, currency, optional institution / short description — no account numbers.

**What the user is supposed to do:** read the guess, optionally retarget the category, then **Approve** via the same human write path (`bulk-override` + optional rule). Unsure (`needs_human`) stays residual. Quotas: `GET /ai/status`. Suggestions are session/UI state, not ledger truth.

---

## 5. Categories

- IDs: canonical `UUID(f"c2000001-0000-4000-8000-{n:012d}")`; user-created `uuid4()`. **Do not renumber by name.**
- Axes: `parent_id`, `necessity` (Fixed / VariableNecessity / Discretionary), `life_domain`, `is_income`, `is_transfer`, `sort_order`.
- Income vs expense is **not** inferred from the category for dashboard cash totals. Dashboard uses **signed USD amount** (after skipping internals). `is_income` is metadata for the tree (Salary, Other income, Business income).
- **Internal transfers are excluded from spend by the flag**, not by category name. Flagging internals without a category is valid (import core pack / transfer matcher).
- Digital Assets Europe: seed/ensure rule priority 6, description **contains** `Revolut Digital Assets Europe Ltd` → `CAT_CRYPTO_FUND` + `set_internal_transfer`. Import additionally **tags + flags** that narrative without assigning the category.
- Crypto funding **without** the internal flag would count as Investments-domain expense. Product rule: DA Europe cash = internal + Crypto funding.
- Assignable Grok catalog: **leaves only** (no parent nodes, no Other/Uncategorized).
- Archive: `DELETE /categories/{id}` with optional `reassign_to` / `cascade_children`; deactivates rules pointing at archived ids.

Coverage `tx_*` counts **exclude internals**. Other / Uncategorized / `life_domain=Other` = residual, not “real coverage.”

---

## 6. Full transaction row (Google Sheets `Transactions`)

Header order is the sheet contract (`SHEET_HEADERS["Transactions"]` / `Transaction` model):

```382:413:backend/schema/models.py
```

| # | Column | Type / notes | Review table today | Front type today |
|---|--------|----------------|--------------------|------------------|
| 1 | `id` | UUID PK | Hidden (checkbox key) | Yes |
| 2 | `account_id` | UUID | Hidden | Yes |
| 3 | `booking_date` | date | Date column | Yes |
| 4 | `value_date` | optional date | Hidden | Yes (optional) |
| 5 | `amount` | Decimal, **statement-native signed** | Amount via `<Money />` | Yes |
| 6 | `currency` | ISO 3 | Via Money | Yes |
| 7 | `amount_czk` | optional stored historical | Hover secondary only if present | Yes |
| 8 | `amount_usd` | optional stored historical | Same | Yes |
| 9 | `fee_amount` | Decimal, default 0 | Hidden | Yes |
| 10 | `fee_currency` | optional | Hidden | Yes |
| 11 | `merchant` | optional | Description primary | Yes |
| 12 | `description` | optional | Subline if merchant also set | Yes |
| 13 | `original_description` | optional | Search only | Yes |
| 14 | `source_institution` | string | Source column | Yes |
| 15 | `external_id` | optional | Search only | Yes |
| 16 | `counterparty_account` | optional | **Hidden** | **Omitted from TS type** |
| 17 | `counterparty_name` | optional | Search only | Yes |
| 18 | `category_id` | optional UUID | Category `<select>` | Yes |
| 19 | `category_override` | bool | “Recategorized” badge | Yes |
| 20 | `is_internal_transfer` | bool | “Internal” badge | Yes |
| 21 | `transfer_group_id` | optional UUID (paired legs) | Hidden | Yes |
| 22 | `original_file_hash` | SHA-256 of statement | Hidden | **Omitted from TS type** |
| 23 | `source_file_id` | StatementFiles UUID | Hidden | **Omitted from TS type** |
| 24 | `notes` | optional | Hidden | Yes |
| 25 | `suggest_category_id` | optional UUID | Shown as tag name if blank | Yes |
| 26 | `suggest_source` | optional | Hidden | Yes |
| 27 | `suggest_reason` | optional | “Tag: …” if `category_id` null | Yes |
| 28 | `archived` | soft-delete; list API skips | Not listed | **Omitted from TS type** |
| 29 | `created_at` | datetime | Hidden | **Omitted from TS type** |
| 30 | `updated_at` | datetime | Hidden | **Omitted from TS type** |

Review workbench columns: checkbox, date, merchant/description + badges, category select + necessity/domain + tag line, source, signed amount. There is **no row-detail pane** that dumps every sheet column.

`GET /transactions` serializes `Transaction.model_dump(mode="json")` — **all 30 fields are in the JSON** even when the TS type omits some.

---

## 7. Fetching one transaction (or a set) with all sheet columns

**There is no `GET /api/transactions/{id}`.** The only public read is:

```17:45:backend/api/routes/transactions.py
GET /transactions
  date_from, date_to, currency, account_id,
  is_internal_transfer, category_id (UUID only),
  source_file_ids, latest_import_batch,
  ids | tx_ids (comma-separated UUIDs; allowlist, ignores date paging),
  limit (1–5000, default 500), offset
```

When `ids`/`tx_ids` is set, archived rows are still skipped; matching ids are returned as full `model_dump`. Categorize already uses this for vendor / Grok+ ids missing from the newest-3000 page.

Repo already has a single-row read used by **override**, not by GET:

```18:18:backend/sheets/repository.py
def get_by_id(self, tab: str, row_id: UUID) -> SheetRow | None
```

Google implementation: load tab cache, `self._cache[tab].get(row_id)` (`backend/sheets/google_sheets.py`).

**Smallest extension for a full-row detail view:**

1. Prefer **no new backend**: `GET /api/transactions?ids=<uuid>&limit=1` already returns every sheet column. Extend `frontend/src/api/types.ts` `Transaction` with the omitted fields (`counterparty_account`, `original_file_hash`, `source_file_id`, `archived`, `created_at`, `updated_at`) and render the dump.
2. If a dedicated resource is required: thin `GET /api/transactions/{id}` wrapping `repo.get_by_id("Transactions", id)` → 404 if missing/archived → `model_dump`. Do not add a second formula path.

Do not N+1 `get_by_id` per list row; list/allowlist already batches.

---

## 8. Intended human flow (as implied by code) and contradictions

### Intended flow (approved policy + current services)

```
Upload statement
  → SHA-256 idempotency → parse → dedupe
  → core pack TAGS (suggest_*) ; structural own-money may set is_internal_transfer
  → transfer-match may pair legs (flag + transfer_group_id); same currency only; no invented FX
  → persist cash rows with category_id still null
  → user opens Categorize
       1. Categories: ensure/edit the tree (stable UUIDs)
       2. Rules: install generic pack / save patterns (teaching for the *next* apply/import-era apply)
       3. Apply-rules (optional) to paint residuals from saved rules
       4. Review leftovers: vendor buckets → assign one / vendor / similar
          → VendorMemory learns; optional save rule
       5. Grok+: memory (≥2) then tags then leftover model guesses → human Approve
       6. Coverage / Spending / Home read invalidated dashboard (mutations call cache_invalidate)
```

`docs/CATEGORIZE_FLOW.md` AC: import never sets `category_id`; upload reports tagged / internal-flagged / **categorized=0**; Review shows tag reason; Grok+ proposes memory at count≥2.

Coaching (same doc): categories → vendors → one leftover Grok+ batch. Wipe = assigns + VendorMemory only.

### What actually writes meaning

| Stage | Writes `category_id`? | Writes internal flag? |
|-------|----------------------|------------------------|
| Import core pack | No | Yes on structural hits |
| Transfer match | No | Yes on high-confidence pairs |
| Apply-rules / bootstrap-apply / ensure-defaults fill | Yes (residuals) | If rule `set_internal_transfer` |
| Human override / bulk / vendor | Yes | If Internal category or body flag |
| Merchant-queue apply | Yes (ledger-wide contains) | Only if that apply sets it (queue helper does not force) |
| Grok+ / vendor-suggest | **No** | No |
| Wipe | Clears to null | **Kept** |

### Contradictions / traps (do not invent a third policy in UI copy)

1. **Agents.md pipeline** still says `dedupe → categorize → internal transfer match`. Import **removed** `CategoryEngine`. Approved flow is tag-only. Stale user stories (`docs/CATEGORIZE_CURRENT_USER_STORIES.md`) still say “rules auto-apply on new rows.”

2. **Rules exist but do not run at upload.** A user who “saves a rule” is **not** teaching the next import until someone calls apply-rules (or merchant-queue / apply-match). Next import still lands blank + tags.

3. **`apply-match` is global**, not the visible table filter. Copy that implies “apply to these rows” would be false.

4. **Creating a rule ≠ applying it.** Rules mode create/edit/delete does not scan txs. Guided “save a rule?” also persist-only.

5. **First vendor assign does not lock** (`category_override` false). A later fill-blanks/reclassify can move that row. Recategorizing a *real* category does lock.

6. **Merchant-queue apply vs Review vendor apply:** queue creates a `contains` rule and reclassifies **all matching non-override rows** (`mark_override=False`). Review vendor apply only updates **ids in the bucket** (plus optional separate rule at priority 100).

7. **Residual definitions drift slightly:**
   - Coverage `tx_*` and Review residual: null / Other / Uncategorized / `life_domain=Other` / unknown id; **internals excluded** from counts.
   - Coverage USD / dashboard uncategorized **expense**: no cat or `life_domain=Other` (name “Other income” is Income domain — not residual).
   - AI `is_blank_category`: override **or** null / CAT_OTHER / CAT_UNCATEGORIZED / name other|uncategorized — **does not** treat arbitrary `life_domain=Other` user cats as blank unless those names/ids.

8. **Internal without category** is a first-class import outcome. Hide-transfers (default on Categorize unless `hide_transfers=0`) removes them from Review. They are **done for spend**, not leftover Grok work (plus path drops internals).

9. **Keyword pack vs core pack:** `_KEYWORD_RULES` in `categorization.py` is a large bootstrap dictionary (including personal needles skipped for starter). Core pack is a **tiny** exact-shop + structural list. Do not describe import as applying the keyword pack.

10. **Self-education / owner-name rules** are explicitly not firmware (`ensure_default_categories` reports `self_education_rule: False`). Do not design a flow that assumes personal-name matching.

11. **Grok+ date filters:** plus/vendor-suggest routes pass empty dates — leftovers are **full-ledger residual vendors**, not the Spending window.

12. **3000-row list cap:** Review inbox is not the full ledger. Coverage `tx_*` is. Vendor/Grok ids can be older than the loaded page; detail/filter must use `ids`/`tx_ids`, not assume they are already in `items`.

---

## Designer constraints (facts, not layout)

- Display API money; do not client-sum Categorize rows as Spending.
- Do not treat internals / DA Europe flagged legs as spend.
- Do not invent FX or fill missing `amount_czk`.
- Category pickers use API UUIDs; tokens `uncategorized` / `other_rollup` are UI-only.
- Full ledger-row detail = the 30 Transactions columns above; fetch via existing list-by-ids (or a thin `get_by_id` wrap). No new math.
- Mutations that assign/rules/wipe must remain the listed POST paths so caches invalidate.

Layer reminder: frontend → `/api/*` → services (`categorization`, `ai_categorize`, `vendor_memory`) → engines (`categorize`, `core_pack`, `transfer_match`) → sheets. Next paints these contracts; it does not invent a categorize-only store.
