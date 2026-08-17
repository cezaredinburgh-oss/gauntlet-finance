/**
 * Self-test for Home next work chips (uncategorized % + living pace delta).
 * Rounding must match Spending: Number(x).toFixed(0) — not Math.round / Math.floor.
 * Run: npx --yes tsx src/features/dashboard-next/homeWorkChips.selftest.ts  (from frontend/)
 */
import type { DashboardSummary } from "../../api/types";
import { homeWorkChips } from "./homeWorkChips";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function dash(over: {
  uncategorized_pct?: number;
  pace_pct_living?: number | null;
}): DashboardSummary {
  return {
    spending: {
      uncategorized_pct: over.uncategorized_pct ?? 0,
      uncategorized_expense_usd: "0",
      by_domain: [],
      by_necessity: [],
    },
    pace: {
      spend_30d_usd: "0",
      avg_monthly_6m_usd: "0",
      pace_pct: null,
      pace_pct_living: over.pace_pct_living === undefined ? null : over.pace_pct_living,
    },
  } as unknown as DashboardSummary;
}

const none = homeWorkChips(dash({ uncategorized_pct: 0, pace_pct_living: null }));
assertEq(none.length, 0, "0 uncat + null pace → no chips");

const uncatOnly = homeWorkChips(dash({ uncategorized_pct: 12.4, pace_pct_living: null }));
assertEq(uncatOnly.length, 1, "12.4 uncat only → one chip");
assertEq(uncatOnly[0]?.key, "uncategorized", "uncategorized key");
assertEq(uncatOnly[0]?.label, "12% uncategorized", "12.4 → toFixed(0) 12% uncategorized");
assertEq(
  uncatOnly[0]?.to,
  "/expenses/categorize?category_id=uncategorized",
  "uncategorized → categorize",
);

const paceUp = homeWorkChips(dash({ uncategorized_pct: 0, pace_pct_living: 12.4 }));
assertEq(paceUp.length, 1, "pace 12.4 only → one chip");
assertEq(paceUp[0]?.key, "pace_living", "pace key");
assertEq(paceUp[0]?.label, "Living +12% vs 6m", "pace 12.4 → Living +12% vs 6m");
assertEq(paceUp[0]?.to, "/expenses/spending", "pace → spending");

const paceDown = homeWorkChips(dash({ uncategorized_pct: 0, pace_pct_living: -8 }));
assertEq(paceDown.length, 1, "pace -8 → one chip");
assertEq(paceDown[0]?.label, "Living -8% vs 6m", "pace -8 → Living -8% vs 6m");

const paceZero = homeWorkChips(dash({ uncategorized_pct: 0, pace_pct_living: 0 }));
assertEq(paceZero.length, 1, "pace 0 is non-null → show chip");
assertEq(paceZero[0]?.label, "Living +0% vs 6m", "pace 0 → Living +0% vs 6m");

const paceNull = homeWorkChips(dash({ uncategorized_pct: 0, pace_pct_living: null }));
assertEq(paceNull.some((c) => c.key === "pace_living"), false, "null pace omitted");

const both = homeWorkChips(dash({ uncategorized_pct: 12.4, pace_pct_living: 12.4 }));
assertEq(both.length, 2, "both present → two chips");
assertEq(both[0]?.key, "uncategorized", "uncategorized first");
assertEq(both[1]?.key, "pace_living", "pace second");
assertEq(both[0]?.label, "12% uncategorized", "both: uncat label");
assertEq(both[1]?.label, "Living +12% vs 6m", "both: pace label");

console.log("homeWorkChips.selftest: ok");
