import type { TickerDigest } from "../../../api/types";
import { d } from "../../../lib/money";
import { compareNullableNumber, taxFreeSharePct } from "../holdingsSort";

export type NextSortColumn =
  | "ticker"
  | "qty"
  | "platforms"
  | "last"
  | "mv"
  | "fifoAvg"
  | "cost"
  | "unrealized"
  | "weight"
  | "grade"
  | "share"
  | "unlock"
  | "tranche"
  | "lots";

export type NextSortDir = "asc" | "desc";

export type SortStorage = Pick<Storage, "getItem" | "setItem">;

export const NEXT_SORT_COLUMN_KEY = "gauntlet.holdings.sortColumn";
export const NEXT_SORT_DIR_KEY = "gauntlet.holdings.sortDir";

/** Verify columns that may persist / sort this PR. */
export const VERIFY_SORT_COLUMNS: readonly NextSortColumn[] = [
  "ticker",
  "qty",
  "platforms",
  "last",
  "mv",
  "fifoAvg",
  "unlock",
];

export const VERIFY_DEFAULT_COLUMN: NextSortColumn = "qty";
export const VERIFY_DEFAULT_DIR: NextSortDir = "desc";

const NEXT_SORT_COLUMN_SET = new Set<string>([
  "ticker",
  "qty",
  "platforms",
  "last",
  "mv",
  "fifoAvg",
  "cost",
  "unrealized",
  "weight",
  "grade",
  "share",
  "unlock",
  "tranche",
  "lots",
]);

const GRADE_RANK: Record<string, number> = {
  A: 0,
  B: 1,
  C: 2,
  D: 3,
  F: 4,
  "—": 5,
  "N/A": 5,
};

const TRANCHE_RANK: Record<string, number> = {
  now: 0,
  later_this_year: 1,
  next_year: 2,
  year_after: 3,
};

export function isNextSortColumn(raw: string | null | undefined): raw is NextSortColumn {
  return raw != null && NEXT_SORT_COLUMN_SET.has(raw);
}

/** Honest last/as-of metric: missing_price or no quote sorts as null (last). */
export function lastPriceMetric(t: TickerDigest): number | null {
  if (t.missing_price || t.price_usd == null || t.price_usd === "") return null;
  return d(t.price_usd);
}

/** Honest MV: live quote only. Cost must not stand in (classic compareHoldingsColumn does). */
export function marketValueMetric(t: TickerDigest): number | null {
  if (t.market_value_usd == null || t.market_value_usd === "") return null;
  return d(t.market_value_usd);
}

export function resolveNextSort(
  storedColumn: string | null | undefined,
  storedDir: string | null | undefined,
  allowed: readonly NextSortColumn[] = VERIFY_SORT_COLUMNS,
  defaults: { column: NextSortColumn; dir: NextSortDir } = {
    column: VERIFY_DEFAULT_COLUMN,
    dir: VERIFY_DEFAULT_DIR,
  },
): { column: NextSortColumn; dir: NextSortDir } {
  const validColumn =
    storedColumn != null &&
    isNextSortColumn(storedColumn) &&
    allowed.includes(storedColumn);
  if (!validColumn) {
    return { column: defaults.column, dir: defaults.dir };
  }
  const dir: NextSortDir =
    storedDir === "asc" || storedDir === "desc" ? storedDir : defaults.dir;
  return { column: storedColumn, dir };
}

export function loadPersistedNextSort(
  storage: SortStorage = window.localStorage,
): { column: string | null; dir: string | null } {
  try {
    return {
      column: storage.getItem(NEXT_SORT_COLUMN_KEY),
      dir: storage.getItem(NEXT_SORT_DIR_KEY),
    };
  } catch {
    return { column: null, dir: null };
  }
}

/** Write only after the user clicks a header — never seed on first paint. */
export function savePersistedNextSort(
  column: NextSortColumn,
  dir: NextSortDir,
  storage: SortStorage = window.localStorage,
): void {
  try {
    storage.setItem(NEXT_SORT_COLUMN_KEY, column);
    storage.setItem(NEXT_SORT_DIR_KEY, dir);
  } catch {
    /* ignore */
  }
}

export function resolvePersistedNextSort(
  storage: SortStorage = window.localStorage,
  allowed: readonly NextSortColumn[] = VERIFY_SORT_COLUMNS,
  defaults: { column: NextSortColumn; dir: NextSortDir } = {
    column: VERIFY_DEFAULT_COLUMN,
    dir: VERIFY_DEFAULT_DIR,
  },
): { column: NextSortColumn; dir: NextSortDir } {
  const stored = loadPersistedNextSort(storage);
  return resolveNextSort(stored.column, stored.dir, allowed, defaults);
}

function platformCount(t: TickerDigest): number {
  return t.by_platform.length;
}

function dominantTrancheRank(t: TickerDigest): number {
  if (!t.tax_tranches.length) return 5;
  let bestKey = t.tax_tranches[0].key;
  let bestQty = d(t.tax_tranches[0].quantity);
  for (const x of t.tax_tranches) {
    const q = d(x.quantity);
    if (q > bestQty) {
      bestQty = q;
      bestKey = x.key;
    }
  }
  return TRANCHE_RANK[bestKey] ?? 4;
}

export function compareNextHoldingsColumn(
  a: TickerDigest,
  b: TickerDigest,
  column: NextSortColumn,
  dir: NextSortDir,
): number {
  const mul = dir === "asc" ? 1 : -1;
  let cmp = 0;
  let nullsHandled = false;

  switch (column) {
    case "ticker":
      cmp = a.ticker.localeCompare(b.ticker);
      break;
    case "qty":
      cmp = d(a.quantity_total) - d(b.quantity_total);
      break;
    case "platforms": {
      const ap = platformCount(a);
      const bp = platformCount(b);
      if (ap !== bp) {
        cmp = ap - bp;
        break;
      }
      cmp = Number(a.multi_platform) - Number(b.multi_platform);
      break;
    }
    case "last": {
      const am = lastPriceMetric(a);
      const bm = lastPriceMetric(b);
      const n = compareNullableNumber(am, bm, mul);
      if (am == null || bm == null) {
        if (!(am == null && bm == null)) {
          cmp = n;
          nullsHandled = true;
          break;
        }
      } else {
        cmp = am - bm;
      }
      break;
    }
    case "mv": {
      const am = marketValueMetric(a);
      const bm = marketValueMetric(b);
      const n = compareNullableNumber(am, bm, mul);
      if (am == null || bm == null) {
        if (!(am == null && bm == null)) {
          cmp = n;
          nullsHandled = true;
          break;
        }
      } else {
        cmp = am - bm;
      }
      break;
    }
    case "fifoAvg":
      cmp = d(a.avg_cost_usd) - d(b.avg_cost_usd);
      break;
    case "cost":
      cmp = d(a.cost_basis_usd) - d(b.cost_basis_usd);
      break;
    case "unrealized": {
      const am = a.unrealized_pct;
      const bm = b.unrealized_pct;
      const n = compareNullableNumber(am, bm, mul);
      if (am == null || bm == null) {
        if (!(am == null && bm == null)) {
          cmp = n;
          nullsHandled = true;
          break;
        }
      } else {
        cmp = am - bm;
      }
      break;
    }
    case "weight":
      cmp = a.portfolio_weight_pct - b.portfolio_weight_pct;
      break;
    case "grade":
      cmp = (GRADE_RANK[a.roi_grade] ?? 5) - (GRADE_RANK[b.roi_grade] ?? 5);
      break;
    case "share": {
      const am = a.unrealized_share_pct;
      const bm = b.unrealized_share_pct;
      const n = compareNullableNumber(am, bm, mul);
      if (am == null || bm == null) {
        if (!(am == null && bm == null)) {
          cmp = n;
          nullsHandled = true;
          break;
        }
      } else {
        cmp = am - bm;
      }
      break;
    }
    case "unlock": {
      const af = taxFreeSharePct(a);
      const bf = taxFreeSharePct(b);
      if (af == null || bf == null) {
        const n = compareNullableNumber(af, bf, mul);
        if (!(af == null && bf == null)) {
          cmp = n;
          nullsHandled = true;
          break;
        }
      } else if (af !== bf) {
        cmp = af - bf;
        break;
      }
      const ad = a.next_unlock_date;
      const bd = b.next_unlock_date;
      if (!ad && !bd) cmp = 0;
      else if (!ad) cmp = -1;
      else if (!bd) cmp = 1;
      else cmp = ad.localeCompare(bd);
      break;
    }
    case "tranche":
      cmp = dominantTrancheRank(a) - dominantTrancheRank(b);
      break;
    case "lots":
      cmp = a.open_lot_count - b.open_lot_count;
      break;
    default:
      cmp = 0;
  }

  if (cmp !== 0) return nullsHandled ? cmp : mul * cmp;
  return a.ticker.localeCompare(b.ticker);
}
