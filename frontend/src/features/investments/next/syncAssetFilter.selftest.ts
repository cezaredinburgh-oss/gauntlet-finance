/**
 * Self-test for table ↔ chart asset-filter bijection.
 * Run: npx --yes tsx src/features/investments/next/syncAssetFilter.selftest.ts  (from frontend/)
 */
import {
  applyTableAssetFilter,
  assetFilterFromChartScope,
  chartAssetClassToFilter,
  filterToChartAssetClass,
  rowMatchesAssetFilter,
} from "./syncAssetFilter";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function assert(cond: boolean, msg: string): void {
  if (!cond) throw new Error(msg);
}

// --- casing bijection both directions ---
assertEq(filterToChartAssetClass("stock"), "Stock", "stock → Stock");
assertEq(filterToChartAssetClass("crypto"), "Crypto", "crypto → Crypto");
assertEq(chartAssetClassToFilter("Stock"), "stock", "Stock → stock");
assertEq(chartAssetClassToFilter("Crypto"), "crypto", "Crypto → crypto");
assertEq(
  chartAssetClassToFilter(filterToChartAssetClass("stock")),
  "stock",
  "stock round-trip",
);
assertEq(
  chartAssetClassToFilter(filterToChartAssetClass("crypto")),
  "crypto",
  "crypto round-trip",
);
assertEq(
  filterToChartAssetClass(chartAssetClassToFilter("Stock")),
  "Stock",
  "Stock round-trip",
);
assertEq(
  filterToChartAssetClass(chartAssetClassToFilter("Crypto")),
  "Crypto",
  "Crypto round-trip",
);

assertEq(assetFilterFromChartScope({ kind: "all" }), "all", "Portfolio chip → all");
assertEq(
  assetFilterFromChartScope({ kind: "asset_class", asset_class: "Stock" }),
  "stock",
  "Stocks chip → stock",
);
assertEq(
  assetFilterFromChartScope({ kind: "asset_class", asset_class: "Crypto" }),
  "crypto",
  "Crypto chip → crypto",
);
assertEq(
  assetFilterFromChartScope({ kind: "ticker", ticker: "VWCE" }),
  null,
  "ticker strip does not change table filter",
);

assert(rowMatchesAssetFilter("etf", "stock"), "etf matches stock filter");
assert(rowMatchesAssetFilter("ETF", "stock"), "ETF matches stock filter");
assert(rowMatchesAssetFilter("equity", "stock"), "equity matches stock filter");
assert(rowMatchesAssetFilter("Stock", "stock"), "Stock matches stock filter");
assert(!rowMatchesAssetFilter("crypto", "stock"), "crypto is not stock");
assert(rowMatchesAssetFilter("crypto", "crypto"), "crypto matches crypto filter");
assert(rowMatchesAssetFilter("etf", "all"), "etf matches all");

const book = [
  { ticker: "VWCE", asset_class: "etf" },
  { ticker: "AAPL", asset_class: "Stock" },
  { ticker: "BTC", asset_class: "crypto" },
];

// ETF stays selected (and ticker-scoped) when the table filter becomes Stocks.
{
  const synced = applyTableAssetFilter("stock", {
    chartScope: { kind: "ticker", ticker: "VWCE" },
    selectedTicker: "VWCE",
    tickers: book,
  });
  assertEq(synced.assetFilter, "stock", "etf+stock: filter");
  assertEq(synced.selectedTicker, "VWCE", "etf+stock: row stays selected");
  assertEq(synced.chartScope.kind, "ticker", "etf+stock: keep ticker scope");
  if (synced.chartScope.kind === "ticker") {
    assertEq(synced.chartScope.ticker, "VWCE", "etf+stock: same ticker");
  }
}

// Crypto ticker is filtered out of Stocks → clear selection, chart Stocks chip.
{
  const synced = applyTableAssetFilter("stock", {
    chartScope: { kind: "ticker", ticker: "BTC" },
    selectedTicker: "BTC",
    tickers: book,
  });
  assertEq(synced.assetFilter, "stock", "btc+stock: filter");
  assertEq(synced.selectedTicker, null, "btc+stock: selection cleared");
  assertEq(synced.chartScope.kind, "asset_class", "btc+stock: drop to asset_class");
  if (synced.chartScope.kind === "asset_class") {
    assertEq(synced.chartScope.asset_class, "Stock", "btc+stock: Stocks chip");
  }
}

// All / asset_class scope follows the table chips.
{
  const fromAll = applyTableAssetFilter("crypto", {
    chartScope: { kind: "all" },
    selectedTicker: "AAPL",
    tickers: book,
  });
  assertEq(fromAll.chartScope.kind, "asset_class", "all→crypto: asset_class");
  if (fromAll.chartScope.kind === "asset_class") {
    assertEq(fromAll.chartScope.asset_class, "Crypto", "all→crypto: Crypto");
  }
  assertEq(fromAll.selectedTicker, "AAPL", "all→crypto: selection unchanged");

  const fromClass = applyTableAssetFilter("all", {
    chartScope: { kind: "asset_class", asset_class: "Crypto" },
    selectedTicker: "BTC",
    tickers: book,
  });
  assertEq(fromClass.chartScope.kind, "all", "crypto→all: Portfolio");
  assertEq(fromClass.assetFilter, "all", "crypto→all: filter");
}

console.log("syncAssetFilter.selftest: ok");
