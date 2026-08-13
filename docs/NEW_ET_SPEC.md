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
- Review: coverage, top uncategorized, Uncategorized 30d, Expenses 30d, **Uncategorized All**, **By vendor** rollup (×N, mass-assign or click to list). After assign: **Review similar | Apply to similar | Apply + save rule**. Undo (~20s). No AI desk.
- Workbench: select, select-uncategorized, per-row assign/clear, bulk assign/clear, sort, USD+CZK, Internal transfer sets `is_internal_transfer`.
- Rules: table, edit, remove, **manual create**, institution scope, set-internal-transfer. No starter pack / apply-rules buttons (import still applies rules).
- Categories: list, create, edit name/necessity/life domain, parent/child, income + transfer flags, sort order, delete + optional reassign. No restore-defaults.

## Review overlay (assign → similar → rule)

Primary Review path is **manual assign → similar → rule**. No Grok desk, no presets, no chat.

- After a row or bulk assign, one card offers **Review similar**, **Apply to N similar**, and **Apply + save rule** (one click).
- Similar = same vendor key + same money direction + residual only. Rule is the existing client suggestion (`merchant contains …`).
- Guided card sits **above the table**. Undo toast ~20s.
- Internal transfer category still sets `is_internal_transfer`. Hide-transfers default on.

Old `/expenses/categorize` and `/ai/categorize-suggest` stay frozen.

## Acceptance

See overlay AC1–AC9 (session). Reverse: remove `/new-et` routes + nav + cluster endpoint; old ET untouched.
