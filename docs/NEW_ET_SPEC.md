# New ET — lab Expense-tracking fork

Spec approved 2026-08-13. Implementation lives beside old `/expenses/*`; it does not replace it.

## Problem

Rework categorization without breaking Expense tracking for other accounts (owner, sandbox, tour, tenants).

## Gate

Show New ET only when `user.demo_kind === "lab"` (password lab principal; default email `testaccount@o2.pl` via `LAB_EMAIL`).

**Not** shown for:

- Google / owner account
- Sandbox demo (`demo_kind === "sandbox"`)
- Tour demo (`demo_kind === "tour"`)
- Any other tenant

Nav hide is not enough: `/new-et/*` redirects non-lab users to `/expenses/spending`.

## Surface

| Nav | Routes | Who |
|-----|--------|-----|
| Expense tracking (unchanged) | `/expenses/spending`, `/expenses/categorize`, `/expenses/alerts` | Everyone, including lab |
| **New ET** | `/new-et/spending`, `/new-et/categorize` | Lab only |

Same ledger and APIs. No new backend store.

## Spending (copy as-is)

Timeframe, ≥70% uncategorized banner, category bars + necessity colors + top-25 rollup, Net/Income/Expenses + hovers, empty/error/loading.

**Difference:** bar click and “Categorize” links go to `/new-et/categorize`, not `/expenses/categorize`.

## Categorize (trimmed + Categories mode)

Modes: **Review | Rules | Categories**. “Groups” in product language = **Categories** (no heuristic Groups tab).

- Full ledger (no latest-import banner).
- Filters: dates, category, search, currency, hide transfers, expenses only, **income only**. Chips + clear. No life-domain / fixed / transfer-leak / missing-FX.
- Review: coverage, top uncategorized, Uncategorized 30d, Expenses 30d, **Uncategorized All**, **AI cluster desk**, guided similar→rule, undo (~20s).
- Workbench: select, select-uncategorized, per-row assign/clear, bulk assign/clear, sort, USD+CZK, Internal transfer sets `is_internal_transfer`.
- Rules: table, edit, remove, **manual create**, institution scope, set-internal-transfer. No starter pack / apply-rules buttons (import still applies rules).
- Categories: list, create, edit name/necessity/life domain, parent/child, income + transfer flags, sort order, delete + optional reassign. No restore-defaults.

## Review overlay (AI-first)

Clusters are **created by Grok**, not `buildSmartGroups`. New ET does **not** use lab/sandbox heuristic fallback.

- Hard gate: `AI_ENABLED` + `XAI_API_KEY`. Otherwise a setup card; no fake piles.
- `POST /ai/categorize-clusters` is suggest-only. Sends minimized residual rows (id, date, merchant, short description, sign, currency, rounded amount, institution). No account numbers.
- Piles: title, kind (`vendor` | `near_identical` | `internal_transfer` | `income` | `fee` | `other`), tx ids, optional category, confidence, reason, `needs_human`.
- Prompt: start with large obvious groups, identical/near vendors, obvious pot-to-pot.
- Click pile → focus table. Apply → same guided path as row/bulk assign.
- Guided card sits **above the table**. Undo toast ~20s.
- Pot-to-pot: import matcher unchanged; AI may return `internal_transfer` piles; apply sets Internal transfer + `is_internal_transfer`; hide-transfers default on. No silent auto-flag.

Old `/expenses/categorize` and `/ai/categorize-suggest` stay frozen.

## Acceptance

See overlay AC1–AC9 (session). Reverse: remove `/new-et` routes + nav + cluster endpoint; old ET untouched.
