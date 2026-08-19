# Universal categorize flow

Approved 2026-08-14. Same policy for every account (lab included).

## Flow

```
upload
  → core pack TAGS the row (never writes category_id)
  → structural hits + transfer-match may set is_internal_transfer (flag only)
  → user assigns (table, vendor, similar, Grok+ Approve)
  → VendorMemory learns vendor_key → category
  → Grok+ uses memory (≥2 confirms), then tags, then leftover Grok
```

## Core pack (tags only)

**Structural:** Digital Assets Europe Ltd; pocket / vault / exchanged to|from / between own accounts; ATM / cash withdrawal; loan repayment / interest / credit instalment; metal plan / custody / account maintenance / accounted fee.

**Exact shops:** `spotify` → Spotify; `netflix` → Streaming; `mcdonald's` / `mcdonalds` → Restaurants.

**Not firmware:** owner name, moto, filament, Prague shops, `revolut`→Internal, `top-up`, `to EUR`, Amazon, Apple.

Structural own-money hits **set `is_internal_transfer`** even without a pair (DA Europe, pots). Category stays blank.

## Memory

Tab `VendorMemory`: vendor_key, label, category_id, assign_count, reject_count, source.  
Export: `GET /api/categories/vendor-memory`. Not a repo file.

## AC

Rule-create fill (one-rule residual, Apply this rule day-2) is `docs/categorize-ux-redesign/RULE_LEDGER_APPLY_DESIGN.md`. Upload remains AC1.

1. Import never sets `category_id` on new rows.  
2. Core pack may tag + reason.  
3. Flag internals (core + transfer-match); no category.  
4. Upload reports tagged / internal-flagged / categorized=0.  
5. Review shows tag reason.  
6–8. Assign upserts memory; reject on override of a different tag; Grok+ proposes memory at count≥2.  
9–10. No personal firmware; one pack for all principals.  
11. Old `/expenses/*` UI left in place this slice.  
12. pytest + lint.

## Prune later (not this slice)

Import `CategoryEngine` assign (already removed from upload); `ensure_self_education_rule` on provision (removed from ensure-defaults); Grok+ shop dict (shrunk); starter apply-all; Ask Grok non-plus; teaching only via CategoryRules.

## Build plan (done this slice)

| Wave | What |
|------|------|
| W1 | Transaction suggest_* fields, VendorMemory tab, `engines/core_pack.py` |
| W2 | Import tags only + internal flag; upload counts |
| W3 | Memory upsert on override; Grok+ memory ≥2 then tags then leftovers |
| W4 | New ET tag line; types; tests |

Verify: `pytest` (405 passed) · `cd frontend && npm run lint`

## Coaching UX (2026-08-14)

New users get a 3-step wizard (categories → vendors → one leftover Grok+ batch). Skip is allowed. First leftover run stops after one batch. Wipe clears assigns + VendorMemory only. Coverage is full-ledger plus est. leftover $ to 50/75/90%.
