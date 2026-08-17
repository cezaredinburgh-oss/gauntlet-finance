/**
 * Self-test for Tax next group-by-ticker (display sum only).
 * Run: npx --yes tsx src/features/investments/tax-next/groupDisposals.selftest.ts  (from frontend/)
 */
import type { TaxDisposal } from "../../../api/types";
import { groupDisposalsByTicker } from "./groupDisposals";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function assert(cond: boolean, msg: string): void {
  if (!cond) throw new Error(msg);
}

function row(over: Partial<TaxDisposal> & Pick<TaxDisposal, "id" | "date">): TaxDisposal {
  return {
    ticker: "AAPL",
    realized_gain_czk: "0",
    ...over,
  };
}

const empty = groupDisposalsByTicker([]);
assertEq(empty.length, 0, "empty list");

const mixed = groupDisposalsByTicker([
  row({ id: "b", date: "2024-06-02", ticker: "msft", realized_gain_czk: "10" }),
  row({ id: "a2", date: "2024-01-02", ticker: "AAPL", realized_gain_czk: "3" }),
  row({ id: "z", date: "2024-03-01", ticker: null, realized_gain_czk: "1" }),
  row({ id: "a1", date: "2024-01-02", ticker: "aapl", realized_gain_czk: "2" }),
  row({ id: "a0", date: "2024-01-01", ticker: "AAPL", realized_gain_czk: "5" }),
  row({ id: "n", date: "2024-02-01", ticker: "", realized_gain_czk: "4" }),
]);

assertEq(mixed.length, 3, "three groups: AAPL, MSFT, —");
assertEq(mixed[0]?.ticker, "AAPL", "A–Z: AAPL first");
assertEq(mixed[1]?.ticker, "MSFT", "A–Z: MSFT second");
assertEq(mixed[2]?.ticker, "—", "missing ticker bucket last");

const aapl = mixed[0];
assert(aapl !== undefined, "AAPL group exists");
assertEq(aapl.rows.length, 3, "AAPL rows grouped");
assertEq(aapl.rows[0]?.id, "a0", "date asc: 2024-01-01 first");
assertEq(aapl.rows[1]?.id, "a1", "same date: id asc a1 before a2");
assertEq(aapl.rows[2]?.id, "a2", "same date: id asc a2 last");
assertEq(typeof aapl.gainCzk, "number", "gainCzk is a number");
assertEq(aapl.gainCzk, 10, "AAPL gainCzk 5+2+3");
assertEq(mixed[1]?.gainCzk, 10, "MSFT gainCzk");
assertEq(mixed[2]?.rows.length, 2, "null + empty ticker share —");
assertEq(mixed[2]?.gainCzk, 5, "— gainCzk 1+4");

const guarded = groupDisposalsByTicker([
  row({ id: "n1", date: "2024-01-01", ticker: "XYZ", realized_gain_czk: null }),
  row({ id: "n2", date: "2024-01-02", ticker: "XYZ", realized_gain_czk: undefined }),
  row({ id: "n3", date: "2024-01-03", ticker: "XYZ", realized_gain_czk: "" }),
  row({ id: "n4", date: "2024-01-04", ticker: "XYZ", realized_gain_czk: "7.5" }),
]);
assertEq(guarded.length, 1, "null-guard: one group");
assertEq(typeof guarded[0]?.gainCzk, "number", "null-guard: gainCzk type");
assertEq(guarded[0]?.gainCzk, 7.5, "null / undefined / empty contribute 0");

console.log("groupDisposals.selftest: ok");
