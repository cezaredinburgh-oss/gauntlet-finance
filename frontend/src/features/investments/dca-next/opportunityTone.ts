import type { DcaOpportunityItem } from "../../../api/types";

export type OppTone = "hot" | "strong" | "warm" | "cool";

export function historyIncomplete(
  item: DcaOpportunityItem,
  historyAvailable: boolean,
): boolean {
  return (
    historyAvailable === false ||
    item.pullback_pct == null ||
    item.below_52w_avg_pct == null
  );
}

/**
 * Client garnish only. Missing history cannot paint hot — eligible is a chip, not a color override.
 */
export function opportunityTone(
  item: DcaOpportunityItem,
  rankIndex: number,
  listLength: number,
  historyAvailable: boolean,
): OppTone {
  if (historyIncomplete(item, historyAvailable)) return "cool";

  const rankFrac = listLength <= 1 ? 0 : rankIndex / (listLength - 1);
  const deep =
    item.level === "warn" ||
    item.discount_vs_cost_pct >= 25 ||
    (item.eligible && rankFrac <= 0.2);

  if (item.eligible && deep) return "hot";
  if (item.eligible) return "strong";

  const solidSignal =
    item.signal_a ||
    item.signal_b ||
    item.discount_vs_cost_pct >= 5 ||
    (item.pullback_pct != null && item.pullback_pct >= 10) ||
    (item.below_52w_avg_pct != null && item.below_52w_avg_pct >= 5);

  if (solidSignal || rankFrac <= 0.5) return "warm";
  return "cool";
}
