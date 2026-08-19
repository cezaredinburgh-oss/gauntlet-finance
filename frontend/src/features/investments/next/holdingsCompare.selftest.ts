/**
 * Self-test for next Verify/Wealth/Tax/Daily sort (honest MV / last, numeric qty, persist).
 * Run: npx --yes tsx src/features/investments/next/holdingsCompare.selftest.ts  (from frontend/)
 */
import type { TickerDigest, WindowPerformanceItem } from "../../../api/types";
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
import {
  DAILY_DEFAULT_COLUMN,
  DAILY_DEFAULT_DIR,
  DAILY_SORT_COLUMNS,
  HOLDINGS_COLUMN_VIEW_KEY,
  TAX_DEFAULT_COLUMN,
  TAX_DEFAULT_DIR,
  TAX_SORT_COLUMNS,
  VIEW_DEFAULT_SORT,
  VIEW_SORT_COLUMNS,
  VIEW_TABS,
  WEALTH_DEFAULT_COLUMN,
  WEALTH_DEFAULT_DIR,
  WEALTH_SORT_COLUMNS,
  filterTickersByQuery,
  isHoldingsColumnView,
  loadPersistedColumnView,
  resolvePersistedSortForView,
  resolveSortForView,
  savePersistedColumnView,
  uniqueGradeKeyPairs,
  viewForTaxRunwayFocus,
  type ViewStorage,
} from "./holdingsViews";

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

function sortBy(
  rows: TickerDigest[],
  col: NextSortColumn,
  dir: "asc" | "desc",
  mode: "total" | "annualized" = "total",
  perfByTicker?: Readonly<Record<string, WindowPerformanceItem>>,
): TickerDigest[] {
  return [...rows].sort((a, b) =>
    compareNextHoldingsColumn(a, b, col, dir, mode, perfByTicker),
  );
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

// --- Wealth Unreal. ann. sorts by annualized %, not total unrealized ---
{
  const highTotalLowAnn = digest({
    ticker: "TOTAL",
    unrealized_pct: 80,
    annualized_unrealized_pct: 4,
  });
  const lowTotalHighAnn = digest({
    ticker: "ANN",
    unrealized_pct: 10,
    annualized_unrealized_pct: 45,
  });
  const rows = [highTotalLowAnn, lowTotalHighAnn];
  assertEq(
    tickers(sortBy(rows, "unrealized", "desc", "total")).join(","),
    "TOTAL,ANN",
    "total mode sorts by unrealized_pct",
  );
  assertEq(
    tickers(sortBy(rows, "unrealized", "desc", "annualized")).join(","),
    "ANN,TOTAL",
    "annualized mode sorts by annualized_unrealized_pct",
  );
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

  const kept = resolveNextSort("mv", "asc", VERIFY_SORT_COLUMNS);
  assertEq(kept.column, "mv", "valid Verify column kept");
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

// --- view-default sort: Wealth unrealized desc, Tax unlock desc ---
{
  const wealthUnset = resolveSortForView("wealth", null, null);
  assertEq(wealthUnset.column, WEALTH_DEFAULT_COLUMN, "Wealth unset column");
  assertEq(wealthUnset.dir, WEALTH_DEFAULT_DIR, "Wealth unset dir");
  assertEq(wealthUnset.column, "unrealized", "Wealth default is unrealized");
  assertEq(wealthUnset.dir, "desc", "Wealth default dir is desc");

  const taxUnset = resolveSortForView("tax", null, null);
  assertEq(taxUnset.column, TAX_DEFAULT_COLUMN, "Tax unset column");
  assertEq(taxUnset.dir, TAX_DEFAULT_DIR, "Tax unset dir");
  assertEq(taxUnset.column, "unlock", "Tax default is unlock");
  assertEq(taxUnset.dir, "desc", "Tax default dir is desc");

  const verifyRejectsUnrealized = resolveSortForView("verify", "unrealized", "desc");
  assertEq(verifyRejectsUnrealized.column, "qty", "Verify rejects hidden unrealized");
  assertEq(verifyRejectsUnrealized.dir, "desc", "Verify invalid resets to qty desc");

  const wealthKeeps = resolveSortForView("wealth", "unrealized", "asc");
  assertEq(wealthKeeps.column, "unrealized", "Wealth keeps unrealized");
  assertEq(wealthKeeps.dir, "asc", "Wealth keeps dir when column valid");

  const wealthRejectsLast = resolveSortForView("wealth", "last", "asc");
  assertEq(wealthRejectsLast.column, "unrealized", "Wealth rejects Verify-only last");
  assertEq(wealthRejectsLast.dir, "desc", "Wealth invalid resets to default dir");

  const taxRejectsUnrealized = resolveSortForView("tax", "unrealized", "desc");
  assertEq(taxRejectsUnrealized.column, "unlock", "Tax rejects hidden unrealized");
  assertEq(taxRejectsUnrealized.dir, "desc", "Tax invalid resets to unlock desc");

  const taxKeepsTranche = resolveSortForView("tax", "tranche", "asc");
  assertEq(taxKeepsTranche.column, "tranche", "Tax keeps tranche");
  assertEq(taxKeepsTranche.dir, "asc", "Tax keeps dir when column valid");

  assert(
    VIEW_SORT_COLUMNS.verify === VERIFY_SORT_COLUMNS,
    "Verify column set is the shared Verify list",
  );
  assert(VIEW_SORT_COLUMNS.wealth === WEALTH_SORT_COLUMNS, "Wealth column set");
  assert(VIEW_SORT_COLUMNS.tax === TAX_SORT_COLUMNS, "Tax column set");
  assertEq(VIEW_DEFAULT_SORT.verify.column, "qty", "VIEW_DEFAULT_SORT verify");
  assertEq(VIEW_DEFAULT_SORT.wealth.column, "unrealized", "VIEW_DEFAULT_SORT wealth");
  assertEq(VIEW_DEFAULT_SORT.tax.column, "unlock", "VIEW_DEFAULT_SORT tax");
  assertEq(VIEW_DEFAULT_SORT.daily.column, "dayPct", "VIEW_DEFAULT_SORT daily");
  assertEq(VIEW_DEFAULT_SORT.daily.dir, "desc", "VIEW_DEFAULT_SORT daily dir");
}

{
  const store = memoryStorage();
  const wealthFromEmpty = resolvePersistedSortForView("wealth", store);
  assertEq(wealthFromEmpty.column, "unrealized", "empty storage Wealth → unrealized");
  assertEq(wealthFromEmpty.dir, "desc", "empty storage Wealth → desc");
  assertEq(loadPersistedNextSort(store).column, null, "Wealth resolve does not seed sort");

  const taxFromEmpty = resolvePersistedSortForView("tax", store);
  assertEq(taxFromEmpty.column, "unlock", "empty storage Tax → unlock");

  savePersistedNextSort("unrealized", "asc", store);
  const wealthOk = resolvePersistedSortForView("wealth", store);
  assertEq(wealthOk.column, "unrealized", "stored unrealized valid on Wealth");
  assertEq(wealthOk.dir, "asc", "stored dir kept on Wealth");

  const verifyRejects = resolvePersistedSortForView("verify", store);
  assertEq(verifyRejects.column, "qty", "same stored unrealized rejected on Verify");

  const taxRejects = resolvePersistedSortForView("tax", store);
  assertEq(taxRejects.column, "unlock", "same stored unrealized rejected on Tax");
}

// --- columnView persist: unset → verify; write only on save ---
{
  function viewStore(initial: Record<string, string> = {}): ViewStorage & {
    writes: Array<[string, string]>;
  } {
    return memoryStorage(initial);
  }

  const unset = viewStore();
  assertEq(loadPersistedColumnView(unset), "verify", "unset columnView is verify");
  assertEq(unset.writes.length, 0, "load columnView does not write");
  assertEq(
    unset.getItem(HOLDINGS_COLUMN_VIEW_KEY),
    null,
    "do not seed columnView on load",
  );

  const garbage = viewStore({ [HOLDINGS_COLUMN_VIEW_KEY]: "mosaic" });
  assertEq(loadPersistedColumnView(garbage), "verify", "invalid columnView → verify");

  savePersistedColumnView("tax", unset);
  assertEq(loadPersistedColumnView(unset), "tax", "saved tax view");
  savePersistedColumnView("wealth", unset);
  assertEq(loadPersistedColumnView(unset), "wealth", "saved wealth view");
  savePersistedColumnView("daily", unset);
  assertEq(loadPersistedColumnView(unset), "daily", "saved daily view");
}

// --- ticker substring filter (client-only) ---
{
  const book = [
    digest({ ticker: "AAPL" }),
    digest({ ticker: "BTC" }),
    digest({ ticker: "ETH" }),
    digest({ ticker: "TSLA" }),
  ];
  assertEq(
    filterTickersByQuery(book, "bt")
      .map((t) => t.ticker)
      .join(","),
    "BTC",
    "substring bt → BTC",
  );
  assertEq(
    filterTickersByQuery(book, "  a  ")
      .map((t) => t.ticker)
      .join(","),
    "AAPL,TSLA",
    "case-insensitive substring a",
  );
  assertEq(
    filterTickersByQuery(book, "").length,
    4,
    "empty query returns the loaded book",
  );
}

// --- grade key: unique roi_grade + label pairs from the loaded book ---
{
  const book = [
    digest({ ticker: "A", roi_grade: "A", roi_grade_label: "Strong" }),
    digest({ ticker: "B", roi_grade: "C", roi_grade_label: "Flat" }),
    digest({ ticker: "C", roi_grade: "A", roi_grade_label: "Strong" }),
    digest({ ticker: "D", roi_grade: "A", roi_grade_label: "Exceptional" }),
  ];
  const pairs = uniqueGradeKeyPairs(book);
  assertEq(pairs.length, 3, "duplicate A/Strong collapsed");
  assertEq(pairs[0]?.grade, "A", "A ranks first");
  assertEq(pairs[0]?.label, "Exceptional", "same grade ordered by label");
  assertEq(pairs[1]?.label, "Strong", "second A label");
  assertEq(pairs[2]?.grade, "C", "C after A");
}

// --- Daily view: persist, default sort, join map, tax-runway ---
{
  assert(isHoldingsColumnView("daily"), "daily is a valid view");
  assert(VIEW_TABS.some((t) => t.id === "daily" && t.label === "Daily"), "Daily tab");
  assert(VIEW_SORT_COLUMNS.daily === DAILY_SORT_COLUMNS, "Daily column set");
  assertEq(DAILY_DEFAULT_COLUMN, "dayPct", "Daily default column");
  assertEq(DAILY_DEFAULT_DIR, "desc", "Daily default dir");

  const dailyUnset = resolveSortForView("daily", null, null);
  assertEq(dailyUnset.column, "dayPct", "Daily unset column is dayPct");
  assertEq(dailyUnset.dir, "desc", "Daily unset dir is desc");

  const dailyKeeps = resolveSortForView("daily", "dayPnl", "asc");
  assertEq(dailyKeeps.column, "dayPnl", "Daily keeps dayPnl");
  assertEq(dailyKeeps.dir, "asc", "Daily keeps dir when column valid");

  const dailyRejectsUnrealized = resolveSortForView("daily", "unrealized", "desc");
  assertEq(dailyRejectsUnrealized.column, "dayPct", "Daily rejects Wealth unrealized");
  assertEq(dailyRejectsUnrealized.dir, "desc", "Daily invalid resets to dayPct desc");

  const verifyRejectsDayPct = resolveSortForView("verify", "dayPct", "desc");
  assertEq(verifyRejectsDayPct.column, "qty", "Verify rejects Daily dayPct");

  const wealthRejectsDayPct = resolveSortForView("wealth", "dayPct", "asc");
  assertEq(wealthRejectsDayPct.column, "unrealized", "Wealth rejects Daily dayPct");

  const taxRejectsDayPnl = resolveSortForView("tax", "dayPnl", "desc");
  assertEq(taxRejectsDayPnl.column, "unlock", "Tax rejects Daily dayPnl");

  const store = memoryStorage();
  const dailyFromEmpty = resolvePersistedSortForView("daily", store);
  assertEq(dailyFromEmpty.column, "dayPct", "empty storage Daily → dayPct");
  assertEq(dailyFromEmpty.dir, "desc", "empty storage Daily → desc");

  savePersistedNextSort("dayPct", "asc", store);
  const dailyOk = resolvePersistedSortForView("daily", store);
  assertEq(dailyOk.column, "dayPct", "stored dayPct valid on Daily");
  assertEq(dailyOk.dir, "asc", "stored dir kept on Daily");

  const verifyRejectsStored = resolvePersistedSortForView("verify", store);
  assertEq(verifyRejectsStored.column, "qty", "stored dayPct rejected on Verify");
}

{
  const dearDigestCheapYahoo = digest({
    ticker: "AAA",
    price_usd: "100",
    market_value_usd: "100",
    missing_price: false,
    quantity_total: "2",
  });
  const cheapDigestDearYahoo = digest({
    ticker: "BBB",
    price_usd: "1",
    market_value_usd: "1",
    missing_price: false,
    quantity_total: "2",
  });
  const noJoin = digest({
    ticker: "MISS",
    price_usd: "999",
    market_value_usd: "999",
    missing_price: false,
  });
  const nullPerf = digest({
    ticker: "NULL",
    price_usd: "500",
    market_value_usd: "500",
    missing_price: false,
  });
  const rows = [dearDigestCheapYahoo, cheapDigestDearYahoo, noJoin, nullPerf];
  const join: Record<string, WindowPerformanceItem> = {
    AAA: {
      ticker: "AAA",
      last_value: "2",
      change_pct: 1,
      change_abs: "0.5",
      pnl_usd: "1.00",
    },
    BBB: {
      ticker: "BBB",
      last_value: "50",
      change_pct: 5,
      change_abs: "5",
      pnl_usd: "10.00",
    },
    NULL: {
      ticker: "NULL",
      last_value: null,
      change_pct: null,
      change_abs: null,
      pnl_usd: null,
    },
  };

  const bareLast = sortBy(rows, "last", "desc");
  assertEq(bareLast[0]?.ticker, "MISS", "bare last uses digest price_usd");

  const emptyJoinLast = sortBy(rows, "last", "desc", "total", {});
  assertEq(
    tickers(emptyJoinLast).join(","),
    "AAA,BBB,MISS,NULL",
    "explicit empty join Last is Yahoo-or-null, not digest price_usd",
  );

  const lastDesc = sortBy(rows, "last", "desc", "total", join);
  assertEq(
    tickers(lastDesc).join(","),
    "BBB,AAA,MISS,NULL",
    "Daily last uses Yahoo last_value, not digest price_usd; nulls last",
  );
  const lastAsc = sortBy(rows, "last", "asc", "total", join);
  assertEq(lastAsc[0]?.ticker, "AAA", "Daily last asc: lowest Yahoo last first");
  assertEq(lastAsc[1]?.ticker, "BBB", "Daily last asc: higher Yahoo last second");
  const lastAscTail = tickers(lastAsc).slice(2).sort().join(",");
  assertEq(lastAscTail, "MISS,NULL", "Daily last nulls last (asc)");

  const pnlDesc = sortBy(rows, "dayPnl", "desc", "total", join);
  assertEq(
    tickers(pnlDesc).join(","),
    "BBB,AAA,MISS,NULL",
    "dayPnl uses perf.pnl_usd; missing/null last",
  );
  const pnlAsc = sortBy(rows, "dayPnl", "asc", "total", join);
  assertEq(pnlAsc[0]?.ticker, "AAA", "dayPnl asc: smaller pnl first");
  const pnlAscTail = tickers(pnlAsc).slice(2).sort().join(",");
  assertEq(pnlAscTail, "MISS,NULL", "dayPnl nulls last (asc)");

  const pctDesc = sortBy(rows, "dayPct", "desc", "total", join);
  assertEq(
    tickers(pctDesc).join(","),
    "BBB,AAA,MISS,NULL",
    "dayPct uses perf.change_pct; missing/null last",
  );
  const pctAsc = sortBy(rows, "dayPct", "asc", "total", join);
  assertEq(pctAsc[0]?.ticker, "AAA", "dayPct asc: smaller pct first");
  const pctAscTail = tickers(pctAsc).slice(2).sort().join(",");
  assertEq(pctAscTail, "MISS,NULL", "dayPct nulls last (asc)");
}

{
  assertEq(viewForTaxRunwayFocus("daily", true), "verify", "tax-runway snaps Daily to verify");
  assertEq(viewForTaxRunwayFocus("wealth", true), "verify", "tax-runway snaps Wealth to verify");
  assertEq(viewForTaxRunwayFocus("tax", true), "tax", "tax-runway keeps Tax");
  assertEq(viewForTaxRunwayFocus("verify", true), "verify", "tax-runway keeps Verify");
  assertEq(viewForTaxRunwayFocus("daily", false), "daily", "no focus keeps Daily");
}

console.log("holdingsCompare.selftest: ok");
