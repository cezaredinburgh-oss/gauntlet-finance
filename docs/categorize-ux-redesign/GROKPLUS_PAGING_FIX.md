# Spec: Grok+ leftover paging + honest Resume

Bug: Ask Grok+ shows **Ready for review** with an empty list; Play looks dead. Leftovers remain on Review.

## Problem

Plus clusters a **volume-sorted prefix** (`fetch_n ≤ 300`) **then** drops `exclude_merchant_keys`. After ~300 sent keys the prefix is empty, the API returns `vendors_sent=[]`, and the client marks `caught_up`. Resume/`start` keep exclude, so Play re-hits the same empty window. Review can still show 1000+ leftover vendors (volume tail past rank 300).

## Goals

1. Each plus call returns the **next remaining leftover merchants after exclude**, not “top 300 minus exclude.”
2. Empty `vendors_sent` means **no leftover keys remain**, not “prefix exhausted.”
3. Resume does **not** wipe exclude (no double-pay).
4. Empty caught-up is not labeled “Ready for review.”

## Non-goals

- New AI endpoint or model change.
- Wiping `sessionStorage` exclude on every Play.
- Changing Review residual / `isResidualCategory` / override rules.
- Changing Grok batch size (still 12 searchable leftovers).
- Non-plus `/vendor-suggest` paging (out of this slice).

## Approach (chosen)

**Slice after exclude.** `cluster_blank_merchants` already scans the full tx list; `limit` only slices the sorted buckets. Filter exclude, then take a remaining window of 200. Keep `/vendor-suggest-plus` and `exclude_merchant_keys`.

Do **not** grow `fetch_n` with `extra_ex + 80` under a 300 cap — that is the wall.

## User-visible behavior

| State | Title | Play | List |
|-------|--------|------|------|
| Running | Working — matching leftovers | Pause | “Still working…” if empty |
| Paused, has guesses | Paused — ready for review | Play | Guess table |
| Caught up, has guesses | Ready for review | Play | Guess table |
| Caught up, no guesses | Caught up | Play retries same exclude | Honest empty: no “use Ask Grok+ to start”; message that there are no leftover vendors left **for this cursor** |
| True leftovers remain beyond prior exclude | Play / next batch | Working then guesses | Next volume page appears |

## Acceptance criteria

- **AC1.** 301 leftover merchants; exclude the top 300 by `(-count, label)`. `plus=True` still returns the 301st (`vendors_sent` or suggestions non-empty).
- **AC2.** Exclude every leftover key → `vendors_sent=[]`, `suggestions=[]`, message “No uncategorized merchants to suggest.”
- **AC3.** Plus still sends ≤12 `merchant_key=` to Grok. Internals still dropped.
- **AC4.** `grokPlusStatusLabel("caught_up", 0)` is not `"Ready for review"`.
- **AC5.** Resume/`start` does not clear exclude or consumed.
- **AC6.** Approving the last guess (`consumeKeys` → 0 buckets) is not titled Ready for review with an empty “start matching” line.
- **AC7.** Restoring `phase=caught_up` with 0 buckets still `started` (status + Play remain).
- **AC8.** Play after empty caught-up may call plus again with the **same** exclude; if still empty, stay caught up with an honest message (no fake Working stuck state).

## API

Unchanged contract: `POST /api/ai/vendor-suggest-plus` + `exclude_merchant_keys`. Semantics of empty `vendors_sent` become “no remaining leftover keys.”

`cluster_blank_merchants(..., limit: int | None, exclude_keys=...)`: `limit is None` returns all ranked leftover buckets. Do not treat `limit=0` as all.

## Security

Suggest-only; `WritableUserDep` unchanged. No new quota bypass. Empty paging must not call Grok.

## Rollout

Ship on `holdings-lab-ux-polish`. No migration. Reverse: revert the two slices. Session exclude in `sessionStorage` remains valid.

## Deferred

- Align no-Grok `vendors_sent` to “keys consumed this batch only” if a later bug shows skipped searchable leftovers.
- Non-plus vendor-suggest paging.
- Hub “new session” that clears exclude on explicit operator reset.
