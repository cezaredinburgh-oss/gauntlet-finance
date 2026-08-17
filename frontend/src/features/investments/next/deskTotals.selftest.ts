/**
 * Self-test for digest-book desk totals (null MV ⇒ hide unrealized).
 * Run: npx --yes tsx src/features/investments/next/deskTotals.selftest.ts  (from frontend/)
 */
import { viewDeskTotals } from "./deskTotals";
import type { TickerDigestsResponse } from "../../../api/types";

type Portfolio = TickerDigestsResponse["portfolio"];

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

const noQuotes: Portfolio = {
  total_cost_basis_usd: "1234.00",
  total_market_value_usd: null,
  unrealized_usd: "0.00",
  unrealized_pct: 0,
};
const noQuotesView = viewDeskTotals(noQuotes);
assertEq(noQuotesView.mvMissing, true, "no-quotes: mvMissing");
assertEq(noQuotesView.mvUsd, null, "no-quotes: mvUsd stays null");
assertEq(noQuotesView.costUsd, "1234.00", "no-quotes: cost passthrough");
assertEq(noQuotesView.unrealizedUsd, null, "no-quotes: unrealizedUsd forced null");
assertEq(noQuotesView.unrealizedPct, null, "no-quotes: unrealizedPct forced null");

const priced: Portfolio = {
  total_cost_basis_usd: "10000.00",
  total_market_value_usd: "12500.50",
  unrealized_usd: "2500.50",
  unrealized_pct: 25.005,
};
const pricedView = viewDeskTotals(priced);
assertEq(pricedView.mvMissing, false, "priced: mvMissing");
assertEq(pricedView.mvUsd, "12500.50", "priced: mv passthrough");
assertEq(pricedView.costUsd, "10000.00", "priced: cost passthrough");
assertEq(pricedView.unrealizedUsd, "2500.50", "priced: unrealizedUsd passthrough");
assertEq(pricedView.unrealizedPct, 25.005, "priced: unrealizedPct passthrough");

const mixed: Portfolio = {
  total_cost_basis_usd: "2000.00",
  total_market_value_usd: "1800.00",
  unrealized_usd: "-200.00",
  unrealized_pct: -10,
};
const mixedView = viewDeskTotals(mixed);
assertEq(mixedView.mvMissing, false, "mixed book: mv non-null is priced");
assertEq(mixedView.mvUsd, "1800.00", "mixed book: mv passthrough");
assertEq(mixedView.costUsd, "2000.00", "mixed book: cost passthrough");
assertEq(mixedView.unrealizedUsd, "-200.00", "mixed book: unrealizedUsd passthrough");
assertEq(mixedView.unrealizedPct, -10, "mixed book: unrealizedPct passthrough");

console.log("deskTotals.selftest: ok");
