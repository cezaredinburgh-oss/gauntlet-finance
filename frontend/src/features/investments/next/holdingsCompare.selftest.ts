/**
 * Self-test for next Verify sort (honest MV / last, numeric qty, persist).
 * Run: npx --yes tsx src/features/investments/next/holdingsCompare.selftest.ts  (from frontend/)
 */
import type { TickerDigest } from "../../../api/types";
import { compareHoldingsColumn } from "../holdingsSort";
import {
  compareNextHoldingsColumn,
  resolveNextSort,
  VERIFY_DEFAULT_COLUMN,
  VERIFY_DEFAULT_DIR,
  VERIFY_SORT_COLUMNS,
  type NextSortColumn,
  type SortStorage,
  loadPersistedNextSort,
  resolvePersistedNextSort,
  savePersistedNextSort,
} from "./holdingsCompare";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function assert(cond: boolean, msg: string): void {
  if (!cond) throw new Error(msg);
}

function digest(
  over: Partial<TickerDigest> & Pick<TickerDigest, "ticker">,
): TickerDigest {
  return {
    quantity_total: "1",
    by_platform: [],
    multi_platform: false,
    price_usd: "10",
    price_as_of: "2026-01-01",
    cost_basis_usd: "10",
    avg_cost_usd: "10",
    market_value_usd: "10",
    unrealized_usd: "0",
    unrealized_pct: 0,
    roi_grade: "C",
    roi_grade_label: "C",
    portfolio_weight_pct: 0,
    unrealized_share_pct: null,
    growth_contribution_pp: null,
    tax_tranches: [],
    next_unlock_date: null,
    next_unlock_quantity: null,
    realized_lifetime_usd: "0",
    open_lot_count: 1,
    missing_price: false,
    first_acquired: null,
    last_acquired: null,
    ...over,
  } as TickerDigest;
}

function tickers(sorted: TickerDigest[]): string[] {
  return sorted.map((t) => t.ticker);
}

function sortBy(rows: TickerDigest[], col: NextSortColumn, dir: "asc" | "desc"): TickerDigest[] {
  return [...rows].sort((a, b) => compareNextHoldingsColumn(a, b, col, dir));
}

function memoryStorage(initial: Record<string, string> = {}): SortStorage & {
  writes: Array<[string, string]>;
} {
  const data = new Map<string, string>(Object.entries(initial));
  const writes: Array<[string, string]> = [];
  return {
    writes,
    getItem(key: string) {
      return data.has(key) ? (data.get(key) as string) : null;
    },
    setItem(key: string, value: string) {
      writes.push([key, value]);
      data.set(key, value);
    },
  };
}

// --- qty is numeric (not string "10" < "2") ---
{
  const rows = [
    digest({ ticker: "SMALL", quantity_total: "2" }),
    digest({ ticker: "BIG", quantity_total: "10" }),
    digest({ ticker: "MID", quantity_total: "5.5" }),
  ];
  assertEq(tickers(sortBy(rows, "qty", "desc")).join(","), "BIG,MID,SMALL", "qty desc numeric");
  assertEq(tickers(sortBy(rows, "qty", "asc")).join(","), "SMALL,MID,BIG", "qty asc numeric");
}

// --- null MV sorts last in both directions (no cost fallback) ---
{
  const pricedSmall = digest({
    ticker: "PX_SMALL",
    market_value_usd: "100",
    cost_basis_usd: "1",
  });
  const pricedBig = digest({
    ticker: "PX_BIG",
    market_value_usd: "500",
    cost_basis_usd: "2",
  });
  const unpricedFatCost = digest({
    ticker: "NO_PX",
    market_value_usd: null,
    cost_basis_usd: "99999",
    missing_price: true,
  });
  const rows = [unpricedFatCost, pricedSmall, pricedBig];
  const desc = sortBy(rows, "mv", "desc");
  const asc = sortBy(rows, "mv", "asc");
  assertEq(tickers(desc).join(","), "PX_BIG,PX_SMALL,NO_PX", "null MV last when desc");
  assertEq(tickers(asc).join(","), "PX_SMALL,PX_BIG,NO_PX", "null MV last when asc");

  // Classic compareHoldingsColumn uses cost fallback — prove we diverge.
  const classicDesc = [...rows].sort((a, b) =>
    compareHoldingsColumn(a, b, "mv", "desc", "total"),
  );
  assertEq(
    classicDesc[0]?.ticker,
    "NO_PX",
    "classic mv desc still promotes fat cost (untouched)",
  );
  assert(
    desc[0]?.ticker !== "NO_PX",
    "next mv desc must not promote unpriced fat cost",
  );
}

// --- missing_price last/as-of sorts last even if a stale price_usd is present ---
{
  const cheap = digest({
    ticker: "CHEAP",
    price_usd: "2",
    price_as_of: "2026-08-01",
    missing_price: false,
  });
  const dear = digest({
    ticker: "DEAR",
    price_usd: "80",
    price_as_of: "2026-08-01",
    missing_price: false,
  });
  const noQuote = digest({
    ticker: "STALE",
    price_usd: "999",
    price_as_of: "2020-01-01",
    missing_price: true,
  });
  const noPxField = digest({
    ticker: "EMPTY",
    price_usd: null,
    price_as_of: null,
    missing_price: false,
  });
  const rows = [noQuote, cheap, dear, noPxField];
  const desc = sortBy(rows, "last", "desc");
  const asc = sortBy(rows, "last", "asc");
  assertEq(desc[0]?.ticker, "DEAR", "last desc: highest live quote first");
  assertEq(desc[1]?.ticker, "CHEAP", "last desc: cheaper live quote second");
  const descTail = tickers(desc).slice(2).sort().join(",");
  assertEq(descTail, "EMPTY,STALE", "missing_price / no quote sort last (desc)");
  assertEq(asc[0]?.ticker, "CHEAP", "last asc: lowest live quote first");
  assertEq(asc[1]?.ticker, "DEAR", "last asc: higher live quote second");
  const ascTail = tickers(asc).slice(2).sort().join(",");
  assertEq(ascTail, "EMPTY,STALE", "missing_price / no quote sort last (asc)");
  assert(
    desc.indexOf(noQuote) > desc.indexOf(cheap),
    "missing_price sorts after live quotes (desc)",
  );
}

// --- persist: unset → Verify default qty desc; unrealized rejected ---
{
  const unset = resolveNextSort(null, null);
  assertEq(unset.column, VERIFY_DEFAULT_COLUMN, "unset persist column is qty");
  assertEq(unset.dir, VERIFY_DEFAULT_DIR, "unset persist dir is desc");
  assertEq(unset.column, "qty", "Verify default column");

  const rejected = resolveNextSort("unrealized", "desc", VERIFY_SORT_COLUMNS);
  assertEq(rejected.column, "qty", "unrealized not in Verify set → qty");
  assertEq(rejected.dir, "desc", "invalid column resets dir to Verify default");

  const kept = resolveNextSort("last", "asc", VERIFY_SORT_COLUMNS);
  assertEq(kept.column, "last", "valid Verify column kept");
  assertEq(kept.dir, "asc", "valid dir kept");

  const garbage = resolveNextSort("not-a-column", "sideways");
  assertEq(garbage.column, "qty", "unknown column → qty");
  assertEq(garbage.dir, "desc", "unknown dir → desc");
}

{
  const store = memoryStorage();
  const before = resolvePersistedNextSort(store);
  assertEq(before.column, "qty", "empty storage resolves qty");
  assertEq(loadPersistedNextSort(store).column, null, "do not seed storage on resolve");
  assertEq((store as { writes: unknown[] }).writes.length, 0, "resolve does not write");

  savePersistedNextSort("mv", "asc", store);
  const after = resolvePersistedNextSort(store);
  assertEq(after.column, "mv", "saved Verify column");
  assertEq(after.dir, "asc", "saved dir");

  savePersistedNextSort("unrealized", "desc", store);
  const afterWealthLeak = resolvePersistedNextSort(store);
  assertEq(afterWealthLeak.column, "qty", "stored unrealized rejected for Verify");
}

console.log("holdingsCompare.selftest: ok");
