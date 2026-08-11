/**
 * Client-only “seen” state for sidebar alert badges.
 * Not synced to Sheets. Keys are content fingerprints so static backend
 * type ids (e.g. large_outflow) re-badge when title/body change.
 */

/** localStorage key (v2 fingerprints). v1 type-id keys are ignored. */
export const ALERTS_SEEN_STORAGE_KEY = "gauntlet.alerts.seenFingerprints.v2";

/** Dispatched on window after seen keys change (Layout listens). */
export const ALERTS_SEEN_EVENT = "gauntlet:alerts-seen-changed";

export type AlertSeenInput = {
  id: string;
  title?: string | null;
  body?: string | null;
};

/** FNV-1a 32-bit hex — compact stable content hash. */
function hash32(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

/**
 * Fingerprint id + title + body so continuous type-id alerts re-badge when
 * the payload changes (new amount, merchant, missing tickers, etc.).
 */
export function alertFingerprint(a: AlertSeenInput): string {
  const id = (a.id || "").trim();
  if (!id) return "";
  const t = (a.title ?? "").trim();
  const b = (a.body ?? "").trim();
  return `${id}:${hash32(`${id}\n${t}\n${b}`)}`;
}

export function loadSeenAlertKeys(): Set<string> {
  try {
    const raw = localStorage.getItem(ALERTS_SEEN_STORAGE_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(
      parsed.filter((x): x is string => typeof x === "string" && x.length > 0),
    );
  } catch {
    return new Set();
  }
}

/** @deprecated alias — returns fingerprint keys, not raw type ids */
export function loadSeenAlertIds(): Set<string> {
  return loadSeenAlertKeys();
}

function persistSeen(seen: Set<string>): boolean {
  try {
    localStorage.setItem(ALERTS_SEEN_STORAGE_KEY, JSON.stringify([...seen]));
    return true;
  } catch {
    /* quota / private mode */
    return false;
  }
}

function notifySeenChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(ALERTS_SEEN_EVENT));
  }
}

/**
 * Mark one alert as seen by content fingerprint.
 * Accepts a full alert-like object or a precomputed fingerprint string.
 * Returns whether the key is now stored as seen.
 */
export function markAlertSeen(a: AlertSeenInput | string): boolean {
  const key = typeof a === "string" ? a.trim() : alertFingerprint(a);
  if (!key) return false;
  const seen = loadSeenAlertKeys();
  if (seen.has(key)) return true;
  seen.add(key);
  const ok = persistSeen(seen);
  if (ok) notifySeenChanged();
  return ok;
}

export function isAlertSeen(a: AlertSeenInput): boolean {
  const key = alertFingerprint(a);
  if (!key) return false;
  return loadSeenAlertKeys().has(key);
}

/** Count alerts that are still active and not yet acknowledged. */
export function countUnseenAlerts(items: AlertSeenInput[]): number {
  const seen = loadSeenAlertKeys();
  let n = 0;
  for (const a of items) {
    const key = alertFingerprint(a);
    if (key && !seen.has(key)) n += 1;
  }
  return n;
}

/**
 * Drop seen fingerprints that are no longer in the active set so storage
 * does not grow forever and a resolved alert can badge again if it returns
 * with the same payload.
 *
 * Empty active lists do **not** wipe storage (avoids glitch empty responses).
 */
export function pruneSeenAlertKeys(active: AlertSeenInput[]): void {
  if (active.length === 0) return;
  const activeKeys = new Set(active.map(alertFingerprint).filter(Boolean));
  const seen = loadSeenAlertKeys();
  let changed = false;
  for (const k of [...seen]) {
    if (!activeKeys.has(k)) {
      seen.delete(k);
      changed = true;
    }
  }
  if (changed) persistSeen(seen);
}

/** @deprecated alias — pass alert objects (not bare type ids) */
export function pruneSeenAlertIds(active: AlertSeenInput[]): void {
  pruneSeenAlertKeys(active);
}
