/**
 * Short-lived undo stack for category assignments on Categorize workspace.
 */

export type TxCategorySnapshot = {
  category_id: string | null;
  category_override: boolean;
  is_internal_transfer: boolean;
};

export type UndoEntry = {
  id: string;
  label: string;
  /** Previous state per transaction id */
  previous: Record<string, TxCategorySnapshot>;
  expiresAt: number;
};

const DEFAULT_TTL_MS = 20_000;

export function createUndoEntry(
  label: string,
  previous: Record<string, TxCategorySnapshot>,
  ttlMs: number = DEFAULT_TTL_MS,
): UndoEntry {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    label,
    previous,
    expiresAt: Date.now() + ttlMs,
  };
}

export function isUndoValid(entry: UndoEntry | null | undefined, now = Date.now()): boolean {
  return Boolean(entry && entry.expiresAt > now && Object.keys(entry.previous).length > 0);
}

export function snapshotFromTx(t: {
  category_id?: string | null;
  category_override?: boolean;
  is_internal_transfer?: boolean;
}): TxCategorySnapshot {
  return {
    category_id: t.category_id ?? null,
    category_override: Boolean(t.category_override),
    is_internal_transfer: Boolean(t.is_internal_transfer),
  };
}
