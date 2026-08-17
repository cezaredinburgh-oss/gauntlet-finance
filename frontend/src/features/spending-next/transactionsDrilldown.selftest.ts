/**
 * Self-test for Spending next Categorize drill URLs.
 * Run: npx --yes tsx src/features/spending-next/transactionsDrilldown.selftest.ts  (from frontend/)
 */
import { transactionsDrilldownUrl } from "./transactionsDrilldown";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function parse(url: string): { path: string; params: URLSearchParams } {
  const q = url.indexOf("?");
  return {
    path: q === -1 ? url : url.slice(0, q),
    params: new URLSearchParams(q === -1 ? "" : url.slice(q + 1)),
  };
}

const month = { from: "2026-08-01", to: "2026-08-17" };
const normal = transactionsDrilldownUrl(month, {
  id: "cat-groceries",
  value: 42,
});
if (!normal) throw new Error("normal bar: expected URL, got null");
{
  const { path, params } = parse(normal);
  assertEq(path, "/expenses/categorize", "normal: path");
  assertEq(params.get("hide_transfers"), "1", "normal: hide_transfers=1");
  assertEq(params.get("expenses_only"), "1", "normal: expenses_only=1");
  assertEq(params.get("date_from"), "2026-08-01", "normal: date_from");
  assertEq(params.get("date_to"), "2026-08-17", "normal: date_to");
  assertEq(params.get("category_id"), "cat-groceries", "normal: category_id");
  assertEq(params.has("category_ids"), false, "normal: no category_ids");
}

const allTime = transactionsDrilldownUrl(
  { from: null, to: "2026-08-17" },
  { id: "cat-rent", value: 10 },
);
if (!allTime) throw new Error("all-time: expected URL, got null");
{
  const { params } = parse(allTime);
  assertEq(params.has("date_from"), false, "omit date_from when from is null");
  assertEq(params.get("date_to"), "2026-08-17", "all-time: still sets date_to");
  assertEq(params.get("hide_transfers"), "1", "all-time: hide_transfers=1");
  assertEq(params.get("expenses_only"), "1", "all-time: expenses_only=1");
}

const rollup = transactionsDrilldownUrl(month, {
  id: "other_rollup",
  value: 12,
  rollupIds: ["a", "b", "c"],
});
if (!rollup) throw new Error("rollup: expected URL, got null");
{
  const { params } = parse(rollup);
  assertEq(params.get("category_ids"), "a,b,c", "rollup: category_ids");
  assertEq(params.has("category_id"), false, "rollup: no category_id");
  assertEq(params.get("hide_transfers"), "1", "rollup: hide_transfers=1");
  assertEq(params.get("expenses_only"), "1", "rollup: expenses_only=1");
}

assertEq(
  transactionsDrilldownUrl(month, { id: "other_rollup", value: 5, rollupIds: [] }),
  null,
  "rollup with no ids → null",
);
assertEq(
  transactionsDrilldownUrl(month, { id: "other_rollup", value: 5 }),
  null,
  "rollup missing rollupIds → null",
);
assertEq(
  transactionsDrilldownUrl(month, { id: "cat-x", value: 0 }),
  null,
  "value 0 → null",
);
assertEq(
  transactionsDrilldownUrl(month, { id: "cat-x", value: -1 }),
  null,
  "value < 0 → null",
);
assertEq(
  transactionsDrilldownUrl(month, { id: "", value: 10 }),
  null,
  "missing id → null",
);

console.log("transactionsDrilldown.selftest: ok");
