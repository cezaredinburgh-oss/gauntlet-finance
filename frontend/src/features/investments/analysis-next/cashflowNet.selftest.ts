/**
 * Self-test for Analysis next cashflow net-sign (bought − sold).
 * Run: npx --yes tsx src/features/investments/analysis-next/cashflowNet.selftest.ts  (from frontend/)
 */
import {
  cashflowWindowCaption,
  netSecurityCashUsd,
  sliceCashflowWindow,
  type CashflowRow,
} from "./cashflowNet";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

const twoMonths: CashflowRow[] = [
  { month: "2025-01", bought_usd: "100", sold_usd: "30" },
  { month: "2025-02", bought_usd: "50", sold_usd: "80" },
];

const all = netSecurityCashUsd(twoMonths);
assertEq(all.invested, 150, "bought − sold: invested");
assertEq(all.proceeds, 110, "bought − sold: proceeds");
assertEq(all.netDeployed, 40, "bought − sold: netDeployed is 150 − 110");
assertEq(all.netDeployed === 110 - 150, false, "netDeployed is not sold − bought");

const empty = netSecurityCashUsd([]);
assertEq(empty.invested, 0, "empty series: invested");
assertEq(empty.proceeds, 0, "empty series: proceeds");
assertEq(empty.netDeployed, 0, "empty series: netDeployed");

const eight: CashflowRow[] = [
  { month: "2024-07", bought_usd: "10", sold_usd: "1" },
  { month: "2024-08", bought_usd: "10", sold_usd: "1" },
  { month: "2024-09", bought_usd: "10", sold_usd: "1" },
  { month: "2024-10", bought_usd: "10", sold_usd: "1" },
  { month: "2024-11", bought_usd: "10", sold_usd: "1" },
  { month: "2024-12", bought_usd: "10", sold_usd: "1" },
  { month: "2025-01", bought_usd: "100", sold_usd: "20" },
  { month: "2025-02", bought_usd: "50", sold_usd: "80" },
];

const last6 = sliceCashflowWindow(eight, "6");
assertEq(last6.length, 6, "window 6: length");
assertEq(last6[0]?.month, "2024-09", "window 6: first month");
assertEq(last6[5]?.month, "2025-02", "window 6: last month");

const last6Net = netSecurityCashUsd(last6);
assertEq(last6Net.invested, 190, "window 6: invested");
assertEq(last6Net.proceeds, 104, "window 6: proceeds");
assertEq(last6Net.netDeployed, 86, "window 6: bought − sold");

const allWindow = sliceCashflowWindow(eight, "all");
assertEq(allWindow.length, 8, "window all: length");
assertEq(netSecurityCashUsd(allWindow).invested, 210, "window all: invested");
assertEq(netSecurityCashUsd(allWindow).proceeds, 106, "window all: proceeds");
assertEq(netSecurityCashUsd(allWindow).netDeployed, 104, "window all: bought − sold");

assertEq(sliceCashflowWindow([], "12").length, 0, "window slice of empty series");
assertEq(cashflowWindowCaption("6"), "last 6m", "caption 6m");
assertEq(cashflowWindowCaption("12"), "last 12m", "caption 12m");
assertEq(cashflowWindowCaption("24"), "last 24m", "caption 24m");
assertEq(cashflowWindowCaption("all"), "all", "caption all");

console.log("cashflowNet.selftest: ok");
