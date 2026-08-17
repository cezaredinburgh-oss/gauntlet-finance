import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { TickerDigest, TickerDigestsResponse } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import { cn } from "../lib/cn";
import { formatQty } from "../lib/money";
import {
  comparePerformance,
  filterByAssetClass,
  loadHoldingsSortMode,
  saveHoldingsSortMode,
  type HoldingsAssetFilter,
  type HoldingsSortMode,
  HoldingsDetailPanel,
  PositionHistoryChart,
  type ChartScope,
} from "../features/investments";
import { InvestmentsNextChrome } from "../features/investments/lab-chrome/InvestmentsNextChrome";
import { HoldingsDeskTotals } from "../features/investments/next/HoldingsDeskTotals";
import { HoldingsHonestyStrip } from "../features/investments/next/HoldingsHonestyStrip";
import { HoldingsLotsSection } from "../features/investments/next/HoldingsLotsSection";
import { HoldingsTableNext } from "../features/investments/next/HoldingsTableNext";
import {
  applyTableAssetFilter,
  assetFilterFromChartScope,
} from "../features/investments/next/syncAssetFilter";
import { useTickerLots } from "../features/investments/next/useTickerLots";

function defaultChartScope(tickers: TickerDigest[]): ChartScope | null {
  if (tickers.length > 0) return { kind: "all" };
  return null;
}

/**
 * Lab next Holdings desk: digest-only fetch, honesty strip, full-book totals,
 * table + detail left, live chart right.
 */
export function InvestmentsPageNext() {
  const [searchParams] = useSearchParams();
  const focus = searchParams.get("focus") || "";
  const honestyRef = useRef<HTMLDivElement | null>(null);
  const tableRef = useRef<HTMLDivElement | null>(null);

  const [digestsResponse, setDigestsResponse] = useState<TickerDigestsResponse | null>(
    null,
  );
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [chartScope, setChartScope] = useState<ChartScope | null>(null);
  const [performanceMode, setPerformanceMode] = useState<HoldingsSortMode>(() =>
    loadHoldingsSortMode(),
  );
  const [assetFilter, setAssetFilter] = useState<HoldingsAssetFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [softError, setSoftError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const digestsResponseRef = useRef<TickerDigestsResponse | null>(null);
  digestsResponseRef.current = digestsResponse;

  const setPerformanceModePersist = (mode: HoldingsSortMode) => {
    setPerformanceMode(mode);
    saveHoldingsSortMode(mode);
  };

  function selectTicker(ticker: string) {
    setSelectedTicker(ticker);
    setChartScope({ kind: "ticker", ticker });
  }

  function onTableAssetFilter(next: HoldingsAssetFilter) {
    const synced = applyTableAssetFilter(next, {
      chartScope,
      selectedTicker,
      tickers: digestsResponse?.tickers ?? [],
    });
    setAssetFilter(synced.assetFilter);
    setChartScope(synced.chartScope);
    setSelectedTicker(synced.selectedTicker);
  }

  function onChartScope(scope: ChartScope) {
    setChartScope(scope);
    if (scope.kind === "ticker") {
      setSelectedTicker(scope.ticker);
      return;
    }
    const nextFilter = assetFilterFromChartScope(scope);
    if (nextFilter != null) setAssetFilter(nextFilter);
  }

  const loadGen = useRef(0);

  const load = async (opts?: { quiet?: boolean; preserveSelection?: boolean }) => {
    const quiet = opts?.quiet ?? false;
    const preserveSelection = opts?.preserveSelection ?? false;
    const gen = ++loadGen.current;
    if (!quiet) setLoading(true);
    try {
      const digR = await api.tickerDigests();
      if (gen !== loadGen.current) return;
      setDigestsResponse(digR);
      setError(null);
      setSoftError(null);
      setSelectedTicker((prev) => {
        if (preserveSelection && prev && digR.tickers.some((t) => t.ticker === prev)) {
          return prev;
        }
        if (prev && digR.tickers.some((t) => t.ticker === prev)) return prev;
        const best = [...digR.tickers].sort((a, b) =>
          comparePerformance(a, b, "total"),
        )[0];
        return best?.ticker ?? null;
      });
      setChartScope((prev) => {
        if (preserveSelection && prev) {
          if (prev.kind === "all" && digR.tickers.length > 0) return prev;
          if (
            prev.kind === "ticker" &&
            digR.tickers.some((t) => t.ticker === prev.ticker)
          ) {
            return prev;
          }
          if (prev.kind === "asset_class") {
            const ac = prev.asset_class.toLowerCase();
            if (
              digR.tickers.some((t) => {
                const tac = (t.asset_class || "").toLowerCase();
                if (ac === "stock") {
                  return tac === "stock" || tac === "etf" || tac === "equity";
                }
                return tac === ac;
              })
            ) {
              return prev;
            }
          }
        }
        return defaultChartScope(digR.tickers);
      });
    } catch (e) {
      if (gen !== loadGen.current) return;
      const msg = e instanceof Error ? e.message : "Failed";
      if (quiet && digestsResponseRef.current) {
        setSoftError(msg);
        return;
      }
      setError(msg);
    } finally {
      if (gen === loadGen.current && !quiet) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    return () => {
      loadGen.current += 1;
    };
  }, []);

  useEffect(() => {
    const onPrices = () => {
      void load({ quiet: true, preserveSelection: true });
    };
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, []);

  useEffect(() => {
    if (loading || !focus) return;
    const id = window.setTimeout(() => {
      if (focus === "prices") {
        honestyRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else if (focus === "tax_runway") {
        tableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }, 120);
    return () => window.clearTimeout(id);
  }, [loading, focus, digestsResponse]);

  const digests = digestsResponse?.tickers ?? [];

  const tableRows = useMemo(
    () => filterByAssetClass(digests, assetFilter),
    [digests, assetFilter],
  );

  const selectedDigest = useMemo(
    () => digests.find((t) => t.ticker === selectedTicker) || null,
    [digests, selectedTicker],
  );

  const {
    summary: lotSummary,
    loading: lotsLoading,
    error: lotsError,
    retry: retryLots,
  } = useTickerLots(selectedTicker);

  const chartDigests = useMemo(
    () => [...digests].sort((a, b) => comparePerformance(a, b, performanceMode)),
    [digests, performanceMode],
  );

  const hasHoldings = (digestsResponse?.tickers.length ?? 0) > 0;

  if (loading && !digestsResponse) {
    return (
      <InvestmentsNextChrome active="holdings">
        <PageLoader label="Loading investments…" />
      </InvestmentsNextChrome>
    );
  }

  if (error && !digestsResponse) {
    return (
      <InvestmentsNextChrome active="holdings">
        <EmptyState
          title="Couldn’t load investments"
          description={error}
          action={
            <button type="button" className="btn-primary" onClick={() => void load()}>
              Retry
            </button>
          }
        />
      </InvestmentsNextChrome>
    );
  }

  return (
    <InvestmentsNextChrome active="holdings">
      {softError && digestsResponse && (
        <div className="rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          Couldn’t refresh marks: {softError}
          <button
            type="button"
            className="ml-2 font-semibold underline"
            onClick={() => {
              setSoftError(null);
              void load({ quiet: true, preserveSelection: true });
            }}
          >
            Retry
          </button>
        </div>
      )}

      {!hasHoldings ? (
        <EmptyState
          title="No open lots"
          description="Upload Revolut stocks/crypto or eToro activity to build your portfolio."
          action={
            <Link to="/upload" className="btn-primary">
              Upload statements
            </Link>
          }
        />
      ) : (
        digestsResponse && (
          <>
            <div
              ref={honestyRef}
              className={cn(
                "scroll-mt-24",
                focus === "prices" && "rounded-2xl ring-2 ring-brand/50",
              )}
            >
              <HoldingsHonestyStrip response={digestsResponse} />
            </div>

            <HoldingsDeskTotals portfolio={digestsResponse.portfolio} />

            <div className="grid items-start gap-4 lg:grid-cols-12">
              <div className="space-y-4 lg:col-span-7">
                <div ref={tableRef} className="scroll-mt-24">
                  <HoldingsTableNext
                    rows={tableRows}
                    selectedTicker={selectedTicker}
                    onSelect={selectTicker}
                    performanceMode={performanceMode}
                    onPerformanceMode={setPerformanceModePersist}
                    assetFilter={assetFilter}
                    onAssetFilter={onTableAssetFilter}
                    totalCount={digests.length}
                    highlightTaxFree={focus === "tax_runway"}
                  />
                </div>
                {selectedDigest ? (
                  <div className="space-y-3">
                    <HoldingsDetailPanel
                      digest={selectedDigest}
                      copied={copied}
                      onCopy={async () => {
                        try {
                          await navigator.clipboard.writeText(
                            formatQty(selectedDigest.quantity_total),
                          );
                          setCopied(true);
                          setTimeout(() => setCopied(false), 1500);
                        } catch {
                          /* ignore */
                        }
                      }}
                    />
                    <HoldingsLotsSection
                      summary={lotSummary}
                      loading={lotsLoading}
                      error={lotsError}
                      onRetry={retryLots}
                    />
                  </div>
                ) : (
                  <div className="card flex min-h-[12rem] items-center justify-center p-6 text-sm text-ink-faint">
                    Select a holding to verify quantities
                  </div>
                )}
              </div>
              <div className="lg:col-span-5 lg:sticky lg:top-12 lg:self-start">
                {digests.length > 0 && chartScope && (
                  <PositionHistoryChart
                    digests={chartDigests}
                    scope={chartScope}
                    onScopeChange={onChartScope}
                    variant="embedded"
                  />
                )}
              </div>
            </div>
          </>
        )
      )}
    </InvestmentsNextChrome>
  );
}
