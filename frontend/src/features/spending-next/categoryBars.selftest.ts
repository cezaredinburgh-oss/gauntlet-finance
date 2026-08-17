/**
 * Self-test for Spending next category bars (top 25 + other_rollup).
 * Run: npx --yes tsx src/features/spending-next/categoryBars.selftest.ts  (from frontend/)
 */
import {
  CATEGORY_TOP_N,
  buildCategoryBars,
  categoryChartHeight,
  type CategoryBarInput,
} from "./categoryBars";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function assertDeep(actual: unknown, expected: unknown, msg: string): void {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${msg}: expected ${e}, got ${a}`);
}

function row(
  i: number,
  over: Partial<CategoryBarInput> = {},
): CategoryBarInput {
  return {
    id: over.id ?? `cat-${i}`,
    name: over.name ?? `Cat ${i}`,
    amount_usd: over.amount_usd ?? String(i),
    life_domain: over.life_domain ?? "Life",
    necessity: over.necessity ?? "Discretionary",
    pct_of_spend: over.pct_of_spend ?? i,
  };
}

const empty = buildCategoryBars([]);
assertEq(empty.length, 0, "empty → empty");

const twentyFive = Array.from({ length: 25 }, (_, i) => row(i + 1));
const unchanged = buildCategoryBars(twentyFive);
assertEq(unchanged.length, 25, "≤25 unchanged: length");
assertEq(
  unchanged.some((b) => b.id === "other_rollup"),
  false,
  "≤25 unchanged: no rollup",
);
assertEq(unchanged[0]?.id, "cat-1", "≤25 unchanged: first id");
assertEq(unchanged[24]?.id, "cat-25", "≤25 unchanged: last id");
assertEq(unchanged[24]?.value, 25, "≤25 unchanged: last value is API number");
assertEq(unchanged[24]?.pct, 25, "≤25 unchanged: last pct is API number");

const twentySix = [...twentyFive, row(26, { amount_usd: "4.5", pct_of_spend: 1.25 })];
const rolled26 = buildCategoryBars(twentySix);
assertEq(rolled26.length, 26, "26 → 25 + other_rollup: length");
assertEq(rolled26[25]?.id, "other_rollup", "26 → rollup id");
assertEq(rolled26[25]?.name, "Smaller categories (1)", "26 → rollup name");
assertDeep(rolled26[25]?.rollupIds, ["cat-26"], "26 → rollupIds match tail");
assertDeep(rolled26[25]?.rollupNames, ["Cat 26"], "26 → rollupNames match tail");
assertEq(rolled26[25]?.value, 4.5, "26 → rollup value is API amount_usd");
assertEq(rolled26[25]?.pct, 1.25, "26 → rollup pct is API pct_of_spend");

const tail = [
  row(26, { amount_usd: "10", pct_of_spend: 2.5, name: "Alpha" }),
  row(27, { amount_usd: "3.25", pct_of_spend: 0.75, name: "Beta" }),
  row(28, { amount_usd: "1", pct_of_spend: 0.5, name: "Gamma" }),
];
const many = buildCategoryBars([...twentyFive, ...tail]);
assertEq(many.length, CATEGORY_TOP_N + 1, "28 → 25 + rollup");
assertEq(many[CATEGORY_TOP_N]?.id, "other_rollup", "28 → rollup last");
assertDeep(
  many[CATEGORY_TOP_N]?.rollupIds,
  ["cat-26", "cat-27", "cat-28"],
  "28 → rollupIds match tail",
);
assertDeep(
  many[CATEGORY_TOP_N]?.rollupNames,
  ["Alpha", "Beta", "Gamma"],
  "28 → rollupNames match tail",
);
assertEq(
  many[CATEGORY_TOP_N]?.value,
  10 + 3.25 + 1,
  "28 → rollup value is sum of API amount_usd",
);
assertEq(
  many[CATEGORY_TOP_N]?.pct,
  2.5 + 0.75 + 0.5,
  "28 → rollup pct is sum of API pct_of_spend",
);
assertEq(many[0]?.id, "cat-1", "28 → top row preserved");
assertEq(many[24]?.id, "cat-25", "28 → 25th row preserved");

assertEq(categoryChartHeight(0), 280, "chart height floor 280");
assertEq(categoryChartHeight(1), 280, "chart height 1 row still 280");
assertEq(categoryChartHeight(10), 360, "chart height 10 * 32 + 40");

console.log("categoryBars.selftest: ok");
