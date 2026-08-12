/**
 * Client-only “seen” state for sidebar alert badges.
 * Not synced to Sheets.
 *
 * v3: stable alert **id** + seenAt + level. Body text drift must not rebadge.
 * Quiet for TTL after view; rebadge early on level escalate or new id.
 */

/** localStorage key (v3 id→seenAt map). v1/v2 ignored. */
export const ALERTS_SEEN_STORAGE_KEY = "gauntlet.alerts.seen.v3";

/** Dispatched on window after seen keys change (Layout listens). */
export const ALERTS_SEEN_EVENT = "gauntlet:alerts-seen-changed";

/** Default quiet period after the user views an alert (ms). */
export const ALERT_SEEN_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export type AlertSeenInput = {
  id: string;
  title?: string | null;
  body?: string | null;
  level?: string | null;
};

type SeenEntry = {
  seenAt: number;
  level?: string;
};

type SeenMap = Record<string, SeenEntry>;

const LEVEL_RANK: Record<string, number> = {
  info: 0,
  opportunity: 1,
  warn: 2,
  danger: 3,
};

function levelRank(level: string | null | undefined): number {
  const k = (level || "info").toLowerCase();
  return LEVEL_RANK[k] ?? 0;
}

function loadSeenMap(): SeenMap {
  try {
    const raw = localStorage.getItem(ALERTS_SEEN_STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: SeenMap = {};
    for (const [id, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (!id.trim()) continue;
      if (v && typeof v === "object" && !Array.isArray(v)) {
        const rec = v as { seenAt?: unknown; level?: unknown };
        const seenAt =
          typeof rec.seenAt === "number"
            ? rec.seenAt
            : typeof rec.seenAt === "string"
              ? Date.parse(rec.seenAt)
              : NaN;
        if (!Number.isFinite(seenAt)) continue;
        out[id] = {
          seenAt,
          level: typeof rec.level === "string" ? rec.level : undefined,
        };
      }
    }
    return out;
  } catch {
    return {};
  }
}

function persistSeen(map: SeenMap): boolean {
  try {
    localStorage.setItem(ALERTS_SEEN_STORAGE_KEY, JSON.stringify(map));
    return true;
  } catch {
    return false;
  }
}

function notifySeenChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(ALERTS_SEEN_EVENT));
  }
}

/** @deprecated fingerprint helpers — kept as id-only for back-compat call sites */
export function alertFingerprint(a: AlertSeenInput): string {
  return (a.id || "").trim();
}

export function loadSeenAlertKeys(): Set<string> {
  const map = loadSeenMap();
  const now = Date.now();
  const keys = new Set<string>();
  for (const [id, e] of Object.entries(map)) {
    if (now - e.seenAt <= ALERT_SEEN_TTL_MS) keys.add(id);
  }
  return keys;
}

/** @deprecated alias */
export function loadSeenAlertIds(): Set<string> {
  return loadSeenAlertKeys();
}

/**
 * Mark one alert as seen by stable type id.
 * Accepts a full alert-like object or a bare id string.
 */
export function markAlertSeen(a: AlertSeenInput | string): boolean {
  const id = typeof a === "string" ? a.trim() : (a.id || "").trim();
  if (!id) return false;
  const level =
    typeof a === "string" ? undefined : a.level != null ? String(a.level) : undefined;
  const map = loadSeenMap();
  map[id] = { seenAt: Date.now(), level };
  const ok = persistSeen(map);
  if (ok) notifySeenChanged();
  return ok;
}

/** Mark every alert in the list as seen (same timestamp). */
export function markAllAlertsSeen(items: AlertSeenInput[]): number {
  if (!items.length) return 0;
  const map = loadSeenMap();
  const now = Date.now();
  let n = 0;
  for (const a of items) {
    const id = (a.id || "").trim();
    if (!id) continue;
    map[id] = {
      seenAt: now,
      level: a.level != null ? String(a.level) : undefined,
    };
    n += 1;
  }
  if (n > 0 && persistSeen(map)) notifySeenChanged();
  return n;
}

export function isAlertSeen(a: AlertSeenInput, now = Date.now()): boolean {
  const id = (a.id || "").trim();
  if (!id) return false;
  const map = loadSeenMap();
  const e = map[id];
  if (!e) return false;
  if (now - e.seenAt > ALERT_SEEN_TTL_MS) return false;
  // Rebadge if severity escalated since ack
  if (levelRank(a.level) > levelRank(e.level)) return false;
  return true;
}

/** Count alerts that are still active and not yet acknowledged (within TTL). */
export function countUnseenAlerts(items: AlertSeenInput[], now = Date.now()): number {
  let n = 0;
  for (const a of items) {
    if (!isAlertSeen(a, now)) n += 1;
  }
  return n;
}

/**
 * Drop seen entries whose ids are no longer active, and expire past TTL.
 * Empty active lists do **not** wipe storage (avoids glitch empty responses).
 */
export function pruneSeenAlertKeys(active: AlertSeenInput[]): void {
  if (active.length === 0) return;
  const activeIds = new Set(
    active.map((a) => (a.id || "").trim()).filter(Boolean),
  );
  const map = loadSeenMap();
  const now = Date.now();
  let changed = false;
  for (const id of Object.keys(map)) {
    const e = map[id];
    if (!activeIds.has(id) || now - e.seenAt > ALERT_SEEN_TTL_MS) {
      delete map[id];
      changed = true;
    }
  }
  if (changed) persistSeen(map);
}

/** @deprecated alias */
export function pruneSeenAlertIds(active: AlertSeenInput[]): void {
  pruneSeenAlertKeys(active);
}
