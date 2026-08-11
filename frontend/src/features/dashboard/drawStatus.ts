import type { PortfolioSnapshot } from "../../api/types";
import { d } from "../../lib/money";

/** Mirrors backend SAFE_DRAW_PCT — display-only compact status for Home. */
export const SAFE_DRAW_PCT = 0.04;

export type CompactDrawStatus = {
  livingUsd: number;
  safeUsd: number;
  fourPctUsd: number;
  taxFreeUsd: number;
  ratio: number | null;
  status: "ok" | "warn" | "over" | "n/a";
  /** Short chip label */
  label: string;
  binding: "tax_free" | "pct_rule" | "none";
};

/**
 * Living draw (TTM) vs safe capacity = min(4% × MV, tax-free now).
 * Same identity as backend compute_draw_metrics — no extra API call.
 */
export function compactDrawFromSnap(
  snap: PortfolioSnapshot | null | undefined,
): CompactDrawStatus | null {
  if (!snap?.living_draw_12m) return null;

  const livingUsd = d(snap.living_draw_12m.draw_usd);
  const mv = snap.total_market_value_usd != null ? d(snap.total_market_value_usd) : 0;
  const taxFreeUsd = d(snap.tax_free_now_usd ?? "0");
  const fourPctUsd = mv * SAFE_DRAW_PCT;
  let safeUsd = Math.min(fourPctUsd, taxFreeUsd);
  if (mv <= 0 && taxFreeUsd <= 0) safeUsd = 0;

  let ratio: number | null = null;
  if (safeUsd > 0) {
    ratio = Math.round((livingUsd / safeUsd) * 100) / 100;
  }

  let status: CompactDrawStatus["status"] = "n/a";
  if (safeUsd <= 0) status = "n/a";
  else if (livingUsd <= 0) status = "ok";
  else if (ratio != null && ratio <= 1) status = "ok";
  else if (ratio != null && ratio <= 1.25) status = "warn";
  else status = "over";

  const binding: CompactDrawStatus["binding"] =
    taxFreeUsd <= fourPctUsd ? "tax_free" : "pct_rule";

  const label =
    status === "ok"
      ? livingUsd <= 0
        ? "Draw ok (reinvesting)"
        : "Draw within safe"
      : status === "warn"
        ? "Draw elevated"
        : status === "over"
          ? "Draw over safe"
          : "Draw n/a";

  return {
    livingUsd,
    safeUsd,
    fourPctUsd,
    taxFreeUsd,
    ratio,
    status,
    label,
    binding: safeUsd <= 0 ? "none" : binding,
  };
}
