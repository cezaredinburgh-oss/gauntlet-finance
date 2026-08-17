/**
 * Self-test for DCA next tone: missing history cannot paint hot.
 * Run: npx --yes tsx src/features/investments/dca-next/opportunityTone.selftest.ts  (from frontend/)
 */
import type { DcaOpportunityItem } from "../../../api/types";
import { historyIncomplete, opportunityTone } from "./opportunityTone";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function item(over: Partial<DcaOpportunityItem> = {}): DcaOpportunityItem {
  return {
    ticker: "TEST",
    asset_class: "equity",
    score: 40,
    eligible: true,
    level: "warn",
    discount_vs_cost_pct: 30,
    pullback_pct: 15,
    below_52w_avg_pct: 10,
    signal_a: true,
    signal_b: true,
    mark: "80",
    avg_cost_usd: "100",
    market_value_usd: "800",
    cost_basis_usd: "1000",
    days_since_buy: 90,
    last_buy: "2024-01-01",
    weight_pct: 5,
    gate_blockers: [],
    ...over,
  };
}

const deepEligible = item({
  eligible: true,
  level: "warn",
  discount_vs_cost_pct: 30,
  pullback_pct: 15,
  below_52w_avg_pct: 10,
});

assertEq(historyIncomplete(deepEligible, false), true, "offline board is incomplete");
assertEq(
  opportunityTone(deepEligible, 0, 5, false),
  "cool",
  "offline + eligible + deep discount → cool",
);

assertEq(historyIncomplete(deepEligible, true), false, "priced complete series is complete");
assertEq(
  opportunityTone(deepEligible, 0, 5, true),
  "hot",
  "complete history + eligible + deep → hot",
);

const nullPullback = item({
  eligible: true,
  discount_vs_cost_pct: 30,
  pullback_pct: null,
  below_52w_avg_pct: 10,
});
assertEq(historyIncomplete(nullPullback, true), true, "null 3M series is incomplete");
assertEq(opportunityTone(nullPullback, 0, 5, true), "cool", "null 3M series → cool");

const null52w = item({
  eligible: true,
  discount_vs_cost_pct: 30,
  pullback_pct: 15,
  below_52w_avg_pct: null,
});
assertEq(historyIncomplete(null52w, true), true, "null 52w series is incomplete");
assertEq(opportunityTone(null52w, 0, 5, true), "cool", "null 52w series → cool");

console.log("opportunityTone.selftest: ok");
