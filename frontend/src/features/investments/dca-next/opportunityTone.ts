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

/** Client garnish only. Color follows list rank (server score order), not eligibility. */
export function opportunityTone(
  _item: DcaOpportunityItem,
  rankIndex: number,
  listLength: number,
  _historyAvailable?: boolean,
): OppTone {
  if (listLength <= 1) return "hot";
  const rankFrac = rankIndex / (listLength - 1);
  if (rankFrac <= 0.25) return "hot";
  if (rankFrac <= 0.5) return "strong";
  if (rankFrac <= 0.75) return "warm";
  return "cool";
}
