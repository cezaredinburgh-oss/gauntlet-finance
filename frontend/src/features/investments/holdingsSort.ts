import type { TickerDigest } from "../../api/types";
import { d } from "../../lib/money";

export type HoldingsSortMode = "total" | "annualized";
export type HoldingsSortColumn =
  | "ticker"
  | "mv"
  | "cost"
  | "unrealized"
  | "weight"
  | "grade"
  | "unlock";

export type HoldingsAssetFilter = "all" | "stock" | "crypto";

export const HOLDINGS_SORT_KEY = "gauntlet.holdings.sortMode";

export function loadHoldingsSortMode(): HoldingsSortMode {
  try {
    const raw = localStorage.getItem(HOLDINGS_SORT_KEY);
    if (raw === "annualized" || raw === "total") return raw;
  } catch {
    /* ignore */
  }
  return "total";
}

export function saveHoldingsSortMode(mode: HoldingsSortMode): void {
  try {
    localStorage.setItem(HOLDINGS_SORT_KEY, mode);
  } catch {
    /* ignore */
  }
}

/** Equity book: Stock + ETF + Equity labels (chart Stocks scope + table filter). */
export function isEquityAssetClass(assetClass: string | null | undefined): boolean {
  const ac = (assetClass || "").toLowerCase();
  return ac === "stock" || ac === "etf" || ac === "equity";
}

export function isCryptoAssetClass(assetClass: string | null | undefined): boolean {
  return (assetClass || "").toLowerCase() === "crypto";
}

/**
 * Compare two optional metrics with **nulls always last**, independent of sort direction.
 * Returns signed order for `a` vs `b` when both present (caller multiplies by dir mul for numbers).
 * When either is null, returns +1 / -1 that already places nulls last (do not re-apply mul).
 */
export function compareNullableNumber(
  am: number | null | undefined,
  bm: number | null | undefined,
  mul: number,
): number {
  if (am == null && bm == null) return 0;
  if (am == null) return 1; // a after b
  if (bm == null) return -1; // b after a
  if (am === bm) return 0;
  return mul * (am - bm);
}

/** Best metric first; unpriced / missing metric last; then larger MV/cost, then name. */
export function comparePerformance(
  a: TickerDigest,
  b: TickerDigest,
  mode: HoldingsSortMode,
): number {
  const metric = (t: TickerDigest): number | null => {
    if (mode === "annualized") {
      return t.annualized_unrealized_pct ?? null;
    }
    return t.unrealized_pct ?? null;
  };
  const am = metric(a);
  const bm = metric(b);
  if (am == null && bm == null) {
    /* fall through */
  } else if (am == null) return 1;
  else if (bm == null) return -1;
  else if (bm !== am) return bm - am;

  const mv = (t: TickerDigest) =>
    t.market_value_usd != null ? d(t.market_value_usd) : d(t.cost_basis_usd);
  const mvDiff = mv(b) - mv(a);
  if (mvDiff !== 0) return mvDiff;
  return a.ticker.localeCompare(b.ticker);
}

const GRADE_RANK: Record<string, number> = {
  A: 0,
  B: 1,
  C: 2,
  D: 3,
  F: 4,
  "—": 5,
  "N/A": 5,
};

function taxFreeShareRatio(t: TickerDigest): number | null {
  if (!t.tax_tranches.length) {
    // No tranche detail: unlock null ⇒ treat as fully eligible; else unknown
    if (!t.next_unlock_date) return 1;
    return null;
  }
  const free = t.tax_tranches.find((x) => x.key === "now");
  const freeMv = free ? d(free.market_value_usd) : 0;
  const total =
    t.market_value_usd != null
      ? d(t.market_value_usd)
      : t.tax_tranches.reduce((s, x) => s + d(x.market_value_usd), 0);
  if (total <= 0) {
    // Unpriced: eligible if no pending unlock
    if (!t.next_unlock_date) return 1;
    return 0;
  }
  return freeMv / total;
}

/**
 * Tax-free share of position MV (or cost/tranche mix when unpriced), 0–100.
 * Honest rounding — does not collapse 99% → 100%. Returns 0 when fully locked.
 * null only when tranche data is insufficient to estimate.
 */
export function taxFreeSharePct(t: TickerDigest): number | null {
  const ratio = taxFreeShareRatio(t);
  if (ratio == null) return null;
  return Math.round(ratio * 1000) / 10;
}

export function compareHoldingsColumn(
  a: TickerDigest,
  b: TickerDigest,
  column: HoldingsSortColumn,
  dir: "asc" | "desc",
  performanceMode: HoldingsSortMode,
): number {
  const mul = dir === "asc" ? 1 : -1;
  let cmp = 0;
  let nullsHandled = false;

  switch (column) {
    case "ticker":
      cmp = a.ticker.localeCompare(b.ticker);
      break;
    case "mv": {
      const av = a.market_value_usd != null ? d(a.market_value_usd) : d(a.cost_basis_usd);
      const bv = b.market_value_usd != null ? d(b.market_value_usd) : d(b.cost_basis_usd);
      cmp = av - bv;
      break;
    }
    case "cost":
      cmp = d(a.cost_basis_usd) - d(b.cost_basis_usd);
      break;
    case "unrealized": {
      const am =
        performanceMode === "annualized"
          ? a.annualized_unrealized_pct
          : a.unrealized_pct;
      const bm =
        performanceMode === "annualized"
          ? b.annualized_unrealized_pct
          : b.unrealized_pct;
      const n = compareNullableNumber(am, bm, mul);
      if (am == null || bm == null) {
        cmp = n;
        nullsHandled = true;
      } else {
        cmp = am - bm;
      }
      break;
    }
    case "weight":
      cmp = a.portfolio_weight_pct - b.portfolio_weight_pct;
      break;
    case "grade": {
      const ar = GRADE_RANK[a.roi_grade] ?? 5;
      const br = GRADE_RANK[b.roi_grade] ?? 5;
      cmp = ar - br;
      break;
    }
    case "unlock": {
      // Primary: tax-free share % (what the column shows); nulls last
      const af = taxFreeSharePct(a);
      const bf = taxFreeSharePct(b);
      if (af == null || bf == null) {
        const n = compareNullableNumber(af, bf, mul);
        if (af == null || bf == null) {
          if (!(af == null && bf == null)) {
            cmp = n;
            nullsHandled = true;
            break;
          }
        }
      } else if (af !== bf) {
        cmp = af - bf;
        break;
      }
      // Tie-break: next unlock date (sooner first when asc)
      const ad = a.next_unlock_date;
      const bd = b.next_unlock_date;
      if (!ad && !bd) cmp = 0;
      else if (!ad) cmp = -1; // fully free (no unlock) first when asc
      else if (!bd) cmp = 1;
      else cmp = ad.localeCompare(bd);
      break;
    }
    default:
      cmp = 0;
  }
  if (cmp !== 0) return nullsHandled ? cmp : mul * cmp;
  return a.ticker.localeCompare(b.ticker);
}

export function filterByAssetClass(
  tickers: TickerDigest[],
  filter: HoldingsAssetFilter,
): TickerDigest[] {
  if (filter === "all") return tickers;
  return tickers.filter((t) => {
    if (filter === "stock") return isEquityAssetClass(t.asset_class);
    if (filter === "crypto") return isCryptoAssetClass(t.asset_class);
    return true;
  });
}
