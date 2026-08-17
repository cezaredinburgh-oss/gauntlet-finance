/**
 * Self-test for DCA next tone: color follows rank, not eligibility / history.
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
  "hot",
  "rank 0 stays hot even when history is offline",
);

assertEq(historyIncomplete(deepEligible, true), false, "priced complete series is complete");
assertEq(opportunityTone(deepEligible, 0, 5, true), "hot", "rank 0 of 5 → hot");
assertEq(opportunityTone(deepEligible, 1, 5, true), "hot", "rank 1 of 5 → hot");
assertEq(opportunityTone(deepEligible, 2, 5, true), "strong", "rank 2 of 5 → strong");
assertEq(opportunityTone(deepEligible, 3, 5, true), "warm", "rank 3 of 5 → warm");
assertEq(opportunityTone(deepEligible, 4, 5, true), "cool", "rank 4 of 5 → cool");

const ineligible = item({ eligible: false, gate_blockers: ["cooldown"] });
assertEq(
  opportunityTone(ineligible, 0, 5, true),
  "hot",
  "ineligible #1 is still hot — eligibility is not a color axis",
);

const nullPullback = item({
  eligible: true,
  discount_vs_cost_pct: 30,
  pullback_pct: null,
  below_52w_avg_pct: 10,
});
assertEq(historyIncomplete(nullPullback, true), true, "null 3M series is incomplete");
assertEq(
  opportunityTone(nullPullback, 0, 5, true),
  "hot",
  "null 3M does not mute a top-rank chip",
);

console.log("opportunityTone.selftest: ok");
