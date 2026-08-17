import type { DashboardSummary } from "../../api/types";

export type HomeWorkChip = {
  key: "uncategorized" | "pace_living";
  label: string;
  to: string;
};

/** Living pace is a signed delta vs 6m average — not a 0–100 utilization gauge. */
export function homeWorkChips(dash: DashboardSummary): HomeWorkChip[] {
  const chips: HomeWorkChip[] = [];

  const uncatPct = Number(dash.spending.uncategorized_pct);
  if (uncatPct > 0) {
    chips.push({
      key: "uncategorized",
      label: `${uncatPct.toFixed(0)}% uncategorized`,
      to: "/expenses/categorize?category_id=uncategorized",
    });
  }

  const pacePct = dash.pace.pace_pct_living;
  if (pacePct != null) {
    const n = Number(pacePct);
    chips.push({
      key: "pace_living",
      label: `Living ${n >= 0 ? "+" : ""}${n.toFixed(0)}% vs 6m`,
      to: "/expenses/spending",
    });
  }

  return chips;
}
