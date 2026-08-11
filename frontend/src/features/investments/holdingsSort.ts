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

function taxFreeShare(t: TickerDigest): number {
  const free = t.tax_tranches.find((x) => x.key === "now");
  if (!free) return 0;
  const freeMv = d(free.market_value_usd);
  const total =
    t.market_value_usd != null
      ? d(t.market_value_usd)
      : t.tax_tranches.reduce((s, x) => s + d(x.market_value_usd), 0);
  if (total <= 0) return 0;
  return freeMv / total;
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
      if (performanceMode === "annualized") {
        const am = a.annualized_unrealized_pct;
        const bm = b.annualized_unrealized_pct;
        if (am == null && bm == null) cmp = 0;
        else if (am == null) cmp = 1;
        else if (bm == null) cmp = -1;
        else cmp = am - bm;
      } else {
        const am = a.unrealized_pct;
        const bm = b.unrealized_pct;
        if (am == null && bm == null) cmp = 0;
        else if (am == null) cmp = 1;
        else if (bm == null) cmp = -1;
        else cmp = am - bm;
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
      const ad = a.next_unlock_date;
      const bd = b.next_unlock_date;
      if (!ad && !bd) cmp = 0;
      else if (!ad) cmp = -1; // all eligible first when asc
      else if (!bd) cmp = 1;
      else cmp = ad.localeCompare(bd);
      break;
    }
    default:
      cmp = 0;
  }
  if (cmp !== 0) return mul * cmp;
  return a.ticker.localeCompare(b.ticker);
}

export function filterByAssetClass(
  tickers: TickerDigest[],
  filter: HoldingsAssetFilter,
): TickerDigest[] {
  if (filter === "all") return tickers;
  return tickers.filter((t) => {
    const ac = (t.asset_class || "").toLowerCase();
    if (filter === "stock") return ac === "stock" || ac === "etf" || ac === "equity";
    if (filter === "crypto") return ac === "crypto";
    return true;
  });
}

export function taxFreeSharePct(t: TickerDigest): number | null {
  const share = taxFreeShare(t);
  if (share <= 0 && !t.tax_tranches.some((x) => x.key === "now" && d(x.market_value_usd) > 0)) {
    // If all eligible, next_unlock null often means 100%
    if (!t.next_unlock_date && t.tax_tranches.length) return 100;
    if (share === 0) return null;
  }
  return Math.round(share * 1000) / 10;
}
