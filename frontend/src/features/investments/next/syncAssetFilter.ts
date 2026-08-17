import {
  isCryptoAssetClass,
  isEquityAssetClass,
  type HoldingsAssetFilter,
} from "../holdingsSort";
import type { ChartScope } from "../PositionHistoryChart";

export type AssetFilterTicker = {
  ticker: string;
  asset_class?: string | null;
};

export type SyncedAssetFilter = {
  assetFilter: HoldingsAssetFilter;
  chartScope: ChartScope;
  selectedTicker: string | null;
};

/** Table slugs are lowercase; chart chips use PositionHistoryChart casing. */
export function filterToChartAssetClass(
  filter: Exclude<HoldingsAssetFilter, "all">,
): "Stock" | "Crypto" {
  return filter === "crypto" ? "Crypto" : "Stock";
}

export function chartAssetClassToFilter(
  assetClass: "Stock" | "Crypto",
): Exclude<HoldingsAssetFilter, "all"> {
  return assetClass === "Crypto" ? "crypto" : "stock";
}

export function rowMatchesAssetFilter(
  assetClass: string | null | undefined,
  filter: HoldingsAssetFilter,
): boolean {
  if (filter === "all") return true;
  if (filter === "stock") return isEquityAssetClass(assetClass);
  return isCryptoAssetClass(assetClass);
}

export function chartScopeForFilter(filter: HoldingsAssetFilter): ChartScope {
  if (filter === "all") return { kind: "all" };
  return { kind: "asset_class", asset_class: filterToChartAssetClass(filter) };
}

/** Portfolio / Stocks / Crypto chips only — ticker strip does not change the table filter. */
export function assetFilterFromChartScope(scope: ChartScope): HoldingsAssetFilter | null {
  if (scope.kind === "all") return "all";
  if (scope.kind === "asset_class") return chartAssetClassToFilter(scope.asset_class);
  return null;
}

/**
 * Table All / Stocks / Crypto. Keeps ticker scope when that row is still
 * visible (ETF counts as stock via isEquityAssetClass).
 */
export function applyTableAssetFilter(
  nextFilter: HoldingsAssetFilter,
  current: {
    chartScope: ChartScope | null;
    selectedTicker: string | null;
    tickers: readonly AssetFilterTicker[];
  },
): SyncedAssetFilter {
  const matchingScope = chartScopeForFilter(nextFilter);
  const scope = current.chartScope;

  if (scope?.kind === "ticker") {
    const row = current.tickers.find((t) => t.ticker === scope.ticker);
    if (row && rowMatchesAssetFilter(row.asset_class, nextFilter)) {
      return {
        assetFilter: nextFilter,
        chartScope: scope,
        selectedTicker: current.selectedTicker ?? scope.ticker,
      };
    }
    return {
      assetFilter: nextFilter,
      chartScope: matchingScope,
      selectedTicker: null,
    };
  }

  return {
    assetFilter: nextFilter,
    chartScope: matchingScope,
    selectedTicker: current.selectedTicker,
  };
}
