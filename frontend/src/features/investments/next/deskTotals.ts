import type { TickerDigestsResponse } from "../../../api/types";

export type DeskTotalsView = {
  mvUsd: string | null;
  costUsd: string;
  unrealizedUsd: string | null;
  unrealizedPct: number | null;
  mvMissing: boolean;
};

/** Full-book display fields. Null MV forces unrealized off — never dress cost as a mark. */
export function viewDeskTotals(
  portfolio: TickerDigestsResponse["portfolio"],
): DeskTotalsView {
  const mvMissing = portfolio.total_market_value_usd == null;
  return {
    mvUsd: portfolio.total_market_value_usd,
    costUsd: portfolio.total_cost_basis_usd,
    unrealizedUsd: mvMissing ? null : portfolio.unrealized_usd,
    unrealizedPct: mvMissing ? null : portfolio.unrealized_pct,
    mvMissing,
  };
}
