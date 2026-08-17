import type { CategoryBar } from "./categoryBars";

export type DrillTimeframe = {
  from: string | null;
  to?: string | null;
};

export type DrillBar = Pick<CategoryBar, "id" | "value"> & {
  rollupIds?: string[];
};

/**
 * Same Categorize drill contract as classic Spending:
 * hide_transfers=1, expenses_only=1, date_from omitted when all-time.
 */
export function transactionsDrilldownUrl(
  tf: DrillTimeframe,
  bar: DrillBar,
): string | null {
  if (!bar.id || bar.value <= 0) return null;
  const params = new URLSearchParams();
  if (tf.from) params.set("date_from", tf.from);
  if (tf.to) params.set("date_to", tf.to);
  params.set("hide_transfers", "1");
  params.set("expenses_only", "1");
  if (bar.id === "other_rollup") {
    const ids = bar.rollupIds?.filter(Boolean) ?? [];
    if (!ids.length) return null;
    params.set("category_ids", ids.join(","));
  } else {
    params.set("category_id", bar.id);
  }
  return `/expenses/categorize?${params.toString()}`;
}
