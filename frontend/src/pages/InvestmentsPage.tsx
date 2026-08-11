import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { PortfolioSnapshot, TickerDigest } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import { cn } from "../lib/cn";
import {
  compareHoldingsColumn,
  comparePerformance,
  filterByAssetClass,
  loadHoldingsSortMode,
  saveHoldingsSortMode,
  type HoldingsAssetFilter,
  type HoldingsSortColumn,
  type HoldingsSortMode,
  DcaTeaser,
  HoldingsDetailPanel,
  HoldingsHero,
  HoldingsTable,
  HoldingsWealthBand,
  buildKpiBreakdown,
  InvestmentsPageShell,
  PositionHistoryChart,
  PriceStatusBanner,
  TaxRunwayCard,
  type ChartScope,
} from "../features/investments";

function defaultChartScope(tickers: TickerDigest[]): ChartScope | null {
  if (tickers.length > 0) return { kind: "all" };
  return null;
}

/**
 * Investments Holdings desk — executive hero, wealth band, holdings table + detail,
 * live chart, tax runway, DCA teaser.
 */
export function InvestmentsPage() {
  const [searchParams] = useSearchParams();
  const focus = searchParams.get("focus") || "";
  const taxRunwayRef = useRef<HTMLDivElement | null>(null);
  const pricesRef = useRef<HTMLDivElement | null>(null);

  const [snap, setSnap] = useState<PortfolioSnapshot | null>(null);
  const [digests, setDigests] = useState<TickerDigest[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [chartScope, setChartScope] = useState<ChartScope | null>(null);
  const [performanceMode, setPerformanceMode] = useState<HoldingsSortMode>(() =>
    loadHoldingsSortMode(),
  );
  const [sortColumn, setSortColumn] = useState<HoldingsSortColumn>("unrealized");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [assetFilter, setAssetFilter] = useState<HoldingsAssetFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [softError, setSoftError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const snapRef = useRef<PortfolioSnapshot | null>(null);
  snapRef.current = snap;

  const setPerformanceModePersist = (mode: HoldingsSortMode) => {
    setPerformanceMode(mode);
    saveHoldingsSortMode(mode);
  };

  function selectTicker(ticker: string) {
    setSelectedTicker(ticker);
    setChartScope({ kind: "ticker", ticker });
  }

  function onChartScope(scope: ChartScope) {
    setChartScope(scope);
    if (scope.kind === "ticker") {
      setSelectedTicker(scope.ticker);
    }
  }

  function onSortColumn(col: HoldingsSortColumn) {
    if (sortColumn === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortColumn(col);
      // Default: best first for metrics, A-first for grade, soonest unlock, A-Z ticker
      if (col === "ticker" || col === "grade" || col === "unlock") {
        setSortDir("asc");
      } else {
        setSortDir("desc");
      }
    }
  }

  const load = async (opts?: { quiet?: boolean; preserveSelection?: boolean }) => {
    const quiet = opts?.quiet ?? false;
    const preserveSelection = opts?.preserveSelection ?? false;
    if (!quiet) setLoading(true);
    try {
      const [snapR, digR] = await Promise.all([
        api.investmentsSnapshot(),
        api.tickerDigests(),
      ]);
      setSnap(snapR);
      setDigests(digR.tickers);
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
            if (digR.tickers.some((t) => (t.asset_class || "").toLowerCase() === ac)) {
              return prev;
            }
          }
        }
        return defaultChartScope(digR.tickers);
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed";
      if (quiet && snapRef.current) {
        setSoftError(msg);
        return;
      }
      setError(msg);
    } finally {
      if (!quiet) setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [snapR, digR] = await Promise.all([
          api.investmentsSnapshot(),
          api.tickerDigests(),
        ]);
        if (!cancelled) {
          setSnap(snapR);
          setDigests(digR.tickers);
          setError(null);
          setSoftError(null);
          const best = [...digR.tickers].sort((a, b) =>
            comparePerformance(a, b, "total"),
          )[0];
          setSelectedTicker(best?.ticker ?? null);
          setChartScope(defaultChartScope(digR.tickers));
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
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
      if (focus === "tax_runway") {
        taxRunwayRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else if (focus === "prices") {
        pricesRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }, 120);
    return () => window.clearTimeout(id);
  }, [loading, focus, snap]);

  const tableRows = useMemo(() => {
    const filtered = filterByAssetClass(digests, assetFilter);
    return [...filtered].sort((a, b) =>
      compareHoldingsColumn(a, b, sortColumn, sortDir, performanceMode),
    );
  }, [digests, assetFilter, sortColumn, sortDir, performanceMode]);

  const selectedDigest = useMemo(
    () => digests.find((t) => t.ticker === selectedTicker) || null,
    [digests, selectedTicker],
  );

  const kpiBreakdown = useMemo(() => {
    if (!snap) return null;
    return buildKpiBreakdown(snap, digests);
  }, [snap, digests]);

  // Chart strip uses performance-sorted digests for consistency with ROI chip strip
  const chartDigests = useMemo(
    () => [...digests].sort((a, b) => comparePerformance(a, b, performanceMode)),
    [digests, performanceMode],
  );

  if (loading && !snap) return <PageLoader label="Loading investments…" />;
  if (error && !snap) {
    return <EmptyState title="Couldn’t load investments" description={error} />;
  }

  const hasHoldings = digests.length > 0 || (snap != null && snap.ticker_count > 0);

  return (
    <InvestmentsPageShell
      active="holdings"
      title="Investments"
      subtitle="Portfolio desk · verify holdings · Czech tax runway"
    >
      {softError && snap && (
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
        />
      ) : (
        <>
          {snap && <HoldingsHero snap={snap} />}

          {snap && kpiBreakdown && (
            <HoldingsWealthBand snap={snap} breakdown={kpiBreakdown} />
          )}

          {digests.length > 0 && (
            <div className="grid gap-4 xl:grid-cols-5">
              <div className="xl:col-span-3">
                <HoldingsTable
                  rows={tableRows}
                  selectedTicker={selectedTicker}
                  onSelect={selectTicker}
                  sortColumn={sortColumn}
                  sortDir={sortDir}
                  onSortColumn={onSortColumn}
                  performanceMode={performanceMode}
                  onPerformanceMode={setPerformanceModePersist}
                  assetFilter={assetFilter}
                  onAssetFilter={setAssetFilter}
                  totalCount={digests.length}
                />
              </div>
              <div className="xl:col-span-2">
                {selectedDigest ? (
                  <HoldingsDetailPanel
                    digest={selectedDigest}
                    copied={copied}
                    onCopy={async () => {
                      try {
                        await navigator.clipboard.writeText(selectedDigest.quantity_total);
                        setCopied(true);
                        setTimeout(() => setCopied(false), 1500);
                      } catch {
                        /* ignore */
                      }
                    }}
                  />
                ) : (
                  <div className="card flex min-h-[12rem] items-center justify-center p-6 text-sm text-ink-faint">
                    Select a holding to verify quantities
                  </div>
                )}
              </div>
            </div>
          )}

          {digests.length > 0 && chartScope && (
            <PositionHistoryChart
              digests={chartDigests}
              scope={chartScope}
              onScopeChange={onChartScope}
            />
          )}

          {snap && (
            <TaxRunwayCard snap={snap} focus={focus} runwayRef={taxRunwayRef} />
          )}

          <DcaTeaser />

          {snap && (
            <div
              ref={pricesRef}
              className={cn(
                "scroll-mt-24",
                focus === "prices" && "rounded-2xl ring-2 ring-brand/50",
              )}
            >
              <PriceStatusBanner snap={snap} />
            </div>
          )}
        </>
      )}
    </InvestmentsPageShell>
  );
}
