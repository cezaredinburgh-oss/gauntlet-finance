import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
  HoldingsDetailPanel,
  HoldingsTable,
  InvestmentsPageShell,
  PositionHistoryChart,
  PriceStatusBanner,
  type ChartScope,
} from "../features/investments";

function defaultChartScope(tickers: TickerDigest[]): ChartScope | null {
  if (tickers.length > 0) return { kind: "all" };
  return null;
}

/**
 * Investments Holdings desk:
 * Live chart → holdings table + detail → hero (wealth + tax runway).
 */
export function InvestmentsPage() {
  const [searchParams] = useSearchParams();
  const focus = searchParams.get("focus") || "";
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
      if (col === "ticker" || col === "grade") {
        setSortDir("asc");
      } else {
        setSortDir("desc");
      }
    }
  }

  const loadGen = useRef(0);

  const load = async (opts?: { quiet?: boolean; preserveSelection?: boolean }) => {
    const quiet = opts?.quiet ?? false;
    const preserveSelection = opts?.preserveSelection ?? false;
    const gen = ++loadGen.current;
    if (!quiet) setLoading(true);
    try {
      const [snapR, digR] = await Promise.all([
        api.investmentsSnapshot(),
        api.tickerDigests(),
      ]);
      if (gen !== loadGen.current) return;
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
      if (quiet && snapRef.current) {
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
      if (focus === "prices" || focus === "tax_runway") {
        // tax_runway summary lives on Home; prices banner still on this page
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

  const chartDigests = useMemo(
    () => [...digests].sort((a, b) => comparePerformance(a, b, performanceMode)),
    [digests, performanceMode],
  );

  const hasHoldings = digests.length > 0 || (snap != null && snap.ticker_count > 0);

  if (loading && !snap) {
    return (
      <InvestmentsPageShell
        active="holdings"
        title="Investments"
        subtitle="Portfolio desk · verify holdings · Czech tax runway"
      >
        <PageLoader label="Loading investments…" />
      </InvestmentsPageShell>
    );
  }

  if (error && !snap) {
    return (
      <InvestmentsPageShell
        active="holdings"
        title="Investments"
        subtitle="Portfolio desk · verify holdings · Czech tax runway"
      >
        <EmptyState
          title="Couldn’t load investments"
          description={error}
          action={
            <button type="button" className="btn-primary" onClick={() => void load()}>
              Retry
            </button>
          }
        />
      </InvestmentsPageShell>
    );
  }

  return (
    <InvestmentsPageShell
      active="holdings"
      title="Investments"
      subtitle="Live chart · verify holdings · portfolio summary"
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
          action={
            <Link to="/upload" className="btn-primary">
              Upload statements
            </Link>
          }
        />
      ) : (
        <>
          {digests.length > 0 && chartScope && (
            <PositionHistoryChart
              digests={chartDigests}
              scope={chartScope}
              onScopeChange={onChartScope}
            />
          )}

          {digests.length > 0 && (
            <div className="grid items-start gap-4 xl:grid-cols-5">
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
                  reservedRowCount={digests.length}
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

          {snap && (
            <div
              ref={pricesRef}
              className={cn(
                "scroll-mt-24",
                (focus === "prices" || focus === "tax_runway") &&
                  "rounded-2xl ring-2 ring-brand/50",
              )}
            >
              <PriceStatusBanner snap={snap} />
              {focus === "tax_runway" && (
                <p className="mt-2 text-xs text-ink-muted">
                  Tax-free runway and wealth summary are on the{" "}
                  <Link to="/" className="font-medium text-brand hover:underline">
                    Home
                  </Link>{" "}
                  executive snapshot.
                </p>
              )}
            </div>
          )}
        </>
      )}
    </InvestmentsPageShell>
  );
}
