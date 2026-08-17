import type { TickerDigest } from "../../../api/types";
import {
  type NextSortColumn,
  type NextSortDir,
  type SortStorage,
  VERIFY_DEFAULT_COLUMN,
  VERIFY_DEFAULT_DIR,
  VERIFY_SORT_COLUMNS,
  resolveNextSort,
  resolvePersistedNextSort,
} from "./holdingsCompare";

export type HoldingsColumnView = "verify" | "wealth" | "tax";

export type ViewStorage = Pick<Storage, "getItem" | "setItem">;

/** Unset until the user picks a preset. */
export const HOLDINGS_COLUMN_VIEW_KEY = "gauntlet.holdings.columnView";

export const WEALTH_SORT_COLUMNS: readonly NextSortColumn[] = [
  "ticker",
  "mv",
  "cost",
  "unrealized",
  "weight",
  "grade",
];

export const TAX_SORT_COLUMNS: readonly NextSortColumn[] = [
  "ticker",
  "qty",
  "unlock",
  "tranche",
];

export const WEALTH_DEFAULT_COLUMN: NextSortColumn = "unrealized";
export const WEALTH_DEFAULT_DIR: NextSortDir = "desc";
export const TAX_DEFAULT_COLUMN: NextSortColumn = "unlock";
export const TAX_DEFAULT_DIR: NextSortDir = "desc";

export const VIEW_SORT_COLUMNS: Record<HoldingsColumnView, readonly NextSortColumn[]> = {
  verify: VERIFY_SORT_COLUMNS,
  wealth: WEALTH_SORT_COLUMNS,
  tax: TAX_SORT_COLUMNS,
};

export const VIEW_DEFAULT_SORT: Record<
  HoldingsColumnView,
  { column: NextSortColumn; dir: NextSortDir }
> = {
  verify: { column: VERIFY_DEFAULT_COLUMN, dir: VERIFY_DEFAULT_DIR },
  wealth: { column: WEALTH_DEFAULT_COLUMN, dir: WEALTH_DEFAULT_DIR },
  tax: { column: TAX_DEFAULT_COLUMN, dir: TAX_DEFAULT_DIR },
};

export function isHoldingsColumnView(
  raw: string | null | undefined,
): raw is HoldingsColumnView {
  return raw === "verify" || raw === "wealth" || raw === "tax";
}

/** Read-only. Missing/invalid → verify. Does not write. */
export function loadPersistedColumnView(
  storage: ViewStorage = window.localStorage,
): HoldingsColumnView {
  try {
    const raw = storage.getItem(HOLDINGS_COLUMN_VIEW_KEY);
    if (isHoldingsColumnView(raw)) return raw;
  } catch {
    /* ignore */
  }
  return "verify";
}

/** Write only after the user picks a preset — never seed on first paint. */
export function savePersistedColumnView(
  view: HoldingsColumnView,
  storage: ViewStorage = window.localStorage,
): void {
  try {
    storage.setItem(HOLDINGS_COLUMN_VIEW_KEY, view);
  } catch {
    /* ignore */
  }
}

export function resolveSortForView(
  view: HoldingsColumnView,
  storedColumn: string | null | undefined,
  storedDir: string | null | undefined,
): { column: NextSortColumn; dir: NextSortDir } {
  return resolveNextSort(
    storedColumn,
    storedDir,
    VIEW_SORT_COLUMNS[view],
    VIEW_DEFAULT_SORT[view],
  );
}

export function resolvePersistedSortForView(
  view: HoldingsColumnView,
  storage: SortStorage = window.localStorage,
): { column: NextSortColumn; dir: NextSortDir } {
  return resolvePersistedNextSort(
    storage,
    VIEW_SORT_COLUMNS[view],
    VIEW_DEFAULT_SORT[view],
  );
}

const GRADE_KEY_RANK: Record<string, number> = {
  A: 0,
  B: 1,
  C: 2,
  D: 3,
  F: 4,
};

/** Unique roi_grade + roi_grade_label pairs in the loaded book. */
export function uniqueGradeKeyPairs(
  rows: readonly Pick<TickerDigest, "roi_grade" | "roi_grade_label">[],
): Array<{ grade: string; label: string }> {
  const seen = new Set<string>();
  const out: Array<{ grade: string; label: string }> = [];
  for (const t of rows) {
    const key = `${t.roi_grade}\0${t.roi_grade_label}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ grade: t.roi_grade, label: t.roi_grade_label });
  }
  out.sort((a, b) => {
    const rank = (GRADE_KEY_RANK[a.grade] ?? 5) - (GRADE_KEY_RANK[b.grade] ?? 5);
    if (rank !== 0) return rank;
    return a.label.localeCompare(b.label);
  });
  return out;
}

/** Client ticker substring over already-loaded rows. No API. */
export function filterTickersByQuery(
  rows: readonly TickerDigest[],
  query: string,
): TickerDigest[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...rows];
  return rows.filter((t) => t.ticker.toLowerCase().includes(q));
}
