import type { AuthMe } from "../../../api/types";
import { isLabSession } from "../../../auth/isLabSession";

export type HoldingsDesk = "classic" | "next";

export type DeskStorage = Pick<Storage, "getItem" | "setItem">;

export const HOLDINGS_DESK_KEY = "gauntlet.holdings.desk";
export const HOLDINGS_DESK_DEFAULT: HoldingsDesk = "classic";

export function loadPersistedDesk(
  storage: DeskStorage = window.localStorage,
): HoldingsDesk | null {
  try {
    const raw = storage.getItem(HOLDINGS_DESK_KEY);
    if (raw === "classic" || raw === "next") return raw;
  } catch {
    /* ignore */
  }
  return null;
}

export function savePersistedDesk(
  desk: HoldingsDesk,
  storage: DeskStorage = window.localStorage,
): void {
  try {
    storage.setItem(HOLDINGS_DESK_KEY, desk);
  } catch {
    /* ignore */
  }
}

/** Lab-only. Query wins; persist is read-only here (no writes). */
export function resolveHoldingsDesk(
  user: Pick<AuthMe, "is_demo" | "demo_kind"> | null | undefined,
  searchParams: URLSearchParams,
  storage: DeskStorage = window.localStorage,
): HoldingsDesk {
  if (!isLabSession(user)) return "classic";
  const q = searchParams.get("desk");
  if (q === "classic" || q === "next") return q;
  const stored = loadPersistedDesk(storage);
  if (stored === "classic" || stored === "next") return stored;
  return HOLDINGS_DESK_DEFAULT;
}

/** Merge `desk` into the current query; keep focus and other params. */
export function mergeDeskParam(
  currentSearchParams: URLSearchParams,
  desk: HoldingsDesk,
): URLSearchParams {
  const next = new URLSearchParams(currentSearchParams);
  next.set("desk", desk);
  return next;
}
