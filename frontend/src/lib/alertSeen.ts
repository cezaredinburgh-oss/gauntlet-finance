/** Client-only “seen” state for sidebar alert badges. Not synced to Sheets. */

const STORAGE_KEY = "gauntlet.alerts.seenIds";

/** Dispatched on window after seen ids change (Layout listens). */
export const ALERTS_SEEN_EVENT = "gauntlet:alerts-seen-changed";

export function loadSeenAlertIds(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((x): x is string => typeof x === "string" && x.length > 0));
  } catch {
    return new Set();
  }
}

function persistSeen(seen: Set<string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...seen]));
  } catch {
    /* quota / private mode */
  }
}

/** Mark one alert as seen; no-op if already seen. Notifies listeners. */
export function markAlertSeen(id: string): void {
  if (!id) return;
  const seen = loadSeenAlertIds();
  if (seen.has(id)) return;
  seen.add(id);
  persistSeen(seen);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(ALERTS_SEEN_EVENT));
  }
}

/** Count alerts that are still active and not yet clicked. */
export function countUnseenAlerts(items: Array<{ id: string }>): number {
  const seen = loadSeenAlertIds();
  let n = 0;
  for (const a of items) {
    if (a.id && !seen.has(a.id)) n += 1;
  }
  return n;
}

/**
 * Drop seen ids that are no longer in the active set so storage does not grow
 * forever and a resolved alert can badge again if it reappears later.
 */
export function pruneSeenAlertIds(activeIds: string[]): void {
  const active = new Set(activeIds.filter(Boolean));
  const seen = loadSeenAlertIds();
  let changed = false;
  for (const id of [...seen]) {
    if (!active.has(id)) {
      seen.delete(id);
      changed = true;
    }
  }
  if (changed) persistSeen(seen);
}
