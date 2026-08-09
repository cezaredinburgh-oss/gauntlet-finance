import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Cell,
  ResponsiveContainer,
  Tooltip,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import { Link, useSearchParams } from "react-router-dom";
import { Copy, Check, Layers } from "lucide-react";
import { api } from "../api/client";
import type {
  LivingDraw12m,
  PortfolioSnapshot,
  TickerDigest,
} from "../api/types";
import { Money } from "../components/Money";
import { HoverPanel } from "../components/HoverPanel";
import { EmptyState, PageLoader } from "../components/Spinner";
import { d, formatQty, formatUsd } from "../lib/money";
import { cn } from "../lib/cn";
import {
  InvestmentsSubNav,
  PositionHistoryChart,
  type ChartScope,
} from "../features/investments";

const TAX_TRANCHE_COLORS: Record<string, string> = {
  now: "#2dd4a8",
  later_this_year: "#38bdf8",
  next_year: "#fbbf24",
  year_after: "#f87171",
};

const GRADE_STYLE: Record<string, string> = {
  A: "bg-ok/20 text-ok ring-ok/40",
  B: "bg-brand/20 text-brand ring-brand/40",
  C: "bg-white/10 text-ink ring-white/20",
  D: "bg-warn/20 text-warn ring-warn/40",
  F: "bg-danger/20 text-danger ring-danger/40",
  "—": "bg-white/5 text-ink-faint ring-white/10",
};

/** Soft chip colors by ROI grade (inactive / active). */
const GRADE_CHIP: Record<string, { idle: string; active: string }> = {
  A: {
    idle: "bg-ok/10 text-ok hover:bg-ok/15",
    active: "bg-ok/25 text-ok ring-1 ring-ok/50",
  },
  B: {
    idle: "bg-brand/10 text-brand hover:bg-brand/15",
    active: "bg-brand/25 text-brand ring-1 ring-brand/50",
  },
  C: {
    idle: "bg-white/8 text-ink-muted hover:bg-white/12 hover:text-ink",
    active: "bg-white/15 text-ink ring-1 ring-white/30",
  },
  D: {
    idle: "bg-warn/10 text-warn hover:bg-warn/15",
    active: "bg-warn/25 text-warn ring-1 ring-warn/50",
  },
  F: {
    idle: "bg-danger/10 text-danger hover:bg-danger/15",
    active: "bg-danger/25 text-danger ring-1 ring-danger/50",
  },
  "—": {
    idle: "bg-white/5 text-ink-faint hover:bg-white/10",
    active: "bg-white/10 text-ink-muted ring-1 ring-white/20",
  },
};

const PLATFORM_COLORS = ["#3d9cf0", "#a78bfa", "#fbbf24", "#2dd4a8", "#f87171", "#38bdf8"];

/** Best unrealized ROI first; unpriced last; then larger MV/cost, then name. */
function comparePerformance(a: TickerDigest, b: TickerDigest): number {
  const aPriced = a.unrealized_pct != null;
  const bPriced = b.unrealized_pct != null;
  if (aPriced !== bPriced) return aPriced ? -1 : 1;
  if (aPriced && bPriced && a.unrealized_pct !== b.unrealized_pct) {
    return (b.unrealized_pct as number) - (a.unrealized_pct as number);
  }
  const mv = (t: TickerDigest) =>
    t.market_value_usd != null ? d(t.market_value_usd) : d(t.cost_basis_usd);
  const mvDiff = mv(b) - mv(a);
  if (mvDiff !== 0) return mvDiff;
  return a.ticker.localeCompare(b.ticker);
}

function defaultChartScope(tickers: TickerDigest[]): ChartScope | null {
  if (tickers.length > 0) return { kind: "all" };
  return null;
}

export function InvestmentsPage() {
  const [searchParams] = useSearchParams();
  const focus = searchParams.get("focus") || "";
  const taxRunwayRef = useRef<HTMLDivElement | null>(null);
  const pricesRef = useRef<HTMLDivElement | null>(null);

  const [snap, setSnap] = useState<PortfolioSnapshot | null>(null);
  const [digests, setDigests] = useState<TickerDigest[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [chartScope, setChartScope] = useState<ChartScope | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

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
      setSelectedTicker((prev) => {
        if (preserveSelection && prev && digR.tickers.some((t) => t.ticker === prev)) {
          return prev;
        }
        if (prev && digR.tickers.some((t) => t.ticker === prev)) return prev;
        const best = [...digR.tickers].sort(comparePerformance)[0];
        return best?.ticker ?? null;
      });
      setChartScope((prev) => {
        if (preserveSelection && prev) {
          if (prev.kind === "all" && digR.tickers.length > 0) return prev;
          if (prev.kind === "ticker" && digR.tickers.some((t) => t.ticker === prev.ticker)) {
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
      setError(e instanceof Error ? e.message : "Failed");
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
          const best = [...digR.tickers].sort(comparePerformance)[0];
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

  const sortedDigests = useMemo(
    () => [...digests].sort(comparePerformance),
    [digests],
  );

  const selectedDigest = useMemo(
    () => sortedDigests.find((t) => t.ticker === selectedTicker) || null,
    [sortedDigests, selectedTicker],
  );

  /** Aggregates for KPI hover panels (from snapshot + digests). */
  const kpiBreakdown = useMemo(() => {
    if (!snap) return null;

    const positions = snap.positions || [];
    const withUr = positions
      .filter((p) => p.unrealized_usd != null)
      .map((p) => ({
        ticker: p.ticker,
        unrealized: d(p.unrealized_usd),
        cost: d(p.cost_basis_usd),
        mv: p.market_value != null ? d(p.market_value) : null,
      }));

    const winners = [...withUr]
      .filter((p) => p.unrealized > 0)
      .sort((a, b) => b.unrealized - a.unrealized);
    const losers = [...withUr]
      .filter((p) => p.unrealized < 0)
      .sort((a, b) => a.unrealized - b.unrealized);

    const platformMv = new Map<string, number>();
    const platformCost = new Map<string, number>();
    for (const t of digests) {
      for (const p of t.by_platform) {
        platformMv.set(p.source, (platformMv.get(p.source) || 0) + d(p.market_value_usd));
        platformCost.set(p.source, (platformCost.get(p.source) || 0) + d(p.cost_basis_usd));
      }
    }
    const byPlatformMv = [...platformMv.entries()]
      .map(([source, amount]) => ({ source, amount }))
      .sort((a, b) => b.amount - a.amount);
    const byPlatformCost = [...platformCost.entries()]
      .map(([source, amount]) => ({ source, amount }))
      .sort((a, b) => b.amount - a.amount);

    const topByMv = [...positions]
      .filter((p) => p.market_value != null)
      .map((p) => ({
        ticker: p.ticker,
        mv: d(p.market_value),
        cost: d(p.cost_basis_usd),
      }))
      .sort((a, b) => b.mv - a.mv);

    const topByCost = [...positions]
      .map((p) => ({
        ticker: p.ticker,
        cost: d(p.cost_basis_usd),
        mv: p.market_value != null ? d(p.market_value) : null,
      }))
      .sort((a, b) => b.cost - a.cost);

    const realizedRows = digests
      .map((t) => ({
        ticker: t.ticker,
        realized: d(t.realized_lifetime_usd),
        cost: t.realized_cost_basis_usd != null ? d(t.realized_cost_basis_usd) : null,
        proceeds: t.realized_proceeds_usd != null ? d(t.realized_proceeds_usd) : null,
        roiPct: t.realized_roi_pct ?? null,
      }))
      .filter((r) => r.realized !== 0);
    const realizedWinners = [...realizedRows]
      .filter((r) => r.realized > 0)
      .sort((a, b) => b.realized - a.realized);
    const realizedLosers = [...realizedRows]
      .filter((r) => r.realized < 0)
      .sort((a, b) => a.realized - b.realized);

    const totalMv = snap.total_market_value_usd != null ? d(snap.total_market_value_usd) : null;
    const totalCost = d(snap.total_cost_basis_usd);
    const unrealized = snap.unrealized_usd != null ? d(snap.unrealized_usd) : null;

    return {
      winners,
      losers,
      greenCount: winners.length,
      pricedCount: withUr.length,
      byPlatformMv,
      byPlatformCost,
      topByMv,
      topByCost,
      realizedWinners,
      realizedLosers,
      realizedPositiveCount: realizedWinners.length,
      realizedNegativeCount: realizedLosers.length,
      totalMv,
      totalCost,
      unrealized,
    };
  }, [snap, digests]);

  if (loading) return <PageLoader label="Loading investments…" />;
  if (error) {
    return <EmptyState title="Couldn’t load investments" description={error} />;
  }

  const hasHoldings = digests.length > 0 || (snap != null && snap.ticker_count > 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Investments</h1>
        <p className="text-sm text-ink-muted">
          Market value · Czech 3‑year tax runway · verify holdings
        </p>
        <InvestmentsSubNav active="holdings" />
      </div>

      {!hasHoldings ? (
        <EmptyState
          title="No open lots"
          description="Upload Revolut stocks/crypto or eToro activity to build your portfolio."
        />
      ) : (
        <>
          {digests.length > 0 && chartScope && (
            <PositionHistoryChart
              digests={sortedDigests}
              scope={chartScope}
              onScopeChange={onChartScope}
            />
          )}

          {/* Verify holdings first — primary desk-check workflow */}
          {digests.length > 0 && (
            <div className="card p-5">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h2 className="text-sm font-semibold">Verify holdings</h2>
                  <p className="text-xs text-ink-faint">
                    Select a ticker · compare quantities with your broker apps
                  </p>
                </div>
                <span className="badge bg-white/5 text-ink-muted">
                  {digests.length} tickers
                </span>
              </div>

              <div className="mb-2 flex flex-wrap gap-1.5">
                {sortedDigests.map((t) => {
                  const active = selectedTicker === t.ticker;
                  const grade = t.roi_grade in GRADE_CHIP ? t.roi_grade : "—";
                  const chip = GRADE_CHIP[grade] || GRADE_CHIP["—"];
                  return (
                    <button
                      key={t.ticker}
                      type="button"
                      title={`${t.ticker} · grade ${t.roi_grade} (${t.roi_grade_label})${
                        t.missing_price ? " · no quote" : ""
                      }`}
                      onClick={() => selectTicker(t.ticker)}
                      className={cn(
                        "rounded-lg px-2.5 py-1.5 text-left text-xs font-medium transition",
                        active ? chip.active : chip.idle,
                      )}
                    >
                      <span className="font-semibold">{t.ticker}</span>
                      <span className="ml-1 opacity-70">{formatQty(t.quantity_total)}</span>
                      <span className="ml-1.5 inline-flex h-4 min-w-[1rem] items-center justify-center rounded px-0.5 text-[10px] font-bold opacity-90">
                        {t.roi_grade}
                      </span>
                      {t.multi_platform && (
                        <span
                          className="ml-1 inline-flex items-center opacity-80"
                          title="Multiple platforms"
                        >
                          <Layers className="h-3 w-3" />
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
              <p className="mb-4 text-[11px] text-ink-faint">
                Ordered best → worst ROI · chip color = grade (A–F) · muted = no quote ·{" "}
                <strong className="text-ink-muted">Update prices</strong> for marks
              </p>

              {selectedDigest ? (
                <TickerDigestPanel
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
                <p className="text-sm text-ink-faint">Select a ticker above.</p>
              )}
            </div>
          )}

          {snap && kpiBreakdown && (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                <KpiCard
                  label="Market value"
                  content={
                    <MarketValueBreakdown snap={snap} breakdown={kpiBreakdown} />
                  }
                >
                  {snap.total_market_value_usd ? (
                    <Money
                      amount={snap.total_market_value_usd}
                      currency="USD"
                      secondaryMode="none"
                      size="lg"
                    />
                  ) : (
                    <div className="text-lg text-ink-faint">Update prices</div>
                  )}
                </KpiCard>

                <KpiCard
                  label="Unrealized"
                  content={
                    <UnrealizedBreakdown snap={snap} breakdown={kpiBreakdown} />
                  }
                >
                  {snap.unrealized_usd != null ? (
                    <>
                      <Money
                        amount={snap.unrealized_usd}
                        currency="USD"
                        secondaryMode="none"
                        size="lg"
                        signed
                      />
                      {snap.unrealized_pct != null && (
                        <div
                          className={`text-xs ${
                            snap.unrealized_pct >= 0 ? "text-ok" : "text-danger"
                          }`}
                        >
                          vs open cost {snap.unrealized_pct >= 0 ? "+" : ""}
                          {snap.unrealized_pct.toFixed(1)}%
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="text-lg text-ink-faint">—</div>
                  )}
                </KpiCard>

                <KpiCard
                  label="Realized (FIFO, lifetime)"
                  content={
                    <RealizedBreakdown snap={snap} breakdown={kpiBreakdown} />
                  }
                >
                  <Money
                    amount={snap.realized_lifetime_usd}
                    currency="USD"
                    secondaryMode="none"
                    size="lg"
                    signed
                  />
                  <div className="text-[11px] text-ink-faint">
                    {snap.realized_cost_basis_usd != null &&
                    d(snap.realized_cost_basis_usd) > 0 ? (
                      <>
                        on {formatUsd(snap.realized_cost_basis_usd)} sold cost
                        {snap.realized_roi_pct != null && (
                          <>
                            {" "}
                            · {snap.realized_roi_pct >= 0 ? "+" : ""}
                            {snap.realized_roi_pct.toFixed(0)}%
                          </>
                        )}
                      </>
                    ) : (
                      "Closed lots via FIFO"
                    )}
                  </div>
                </KpiCard>

                <KpiCard
                  label="Open cost basis"
                  content={
                    <CostBasisBreakdown snap={snap} breakdown={kpiBreakdown} />
                  }
                >
                  <Money
                    amount={snap.total_cost_basis_usd}
                    currency="USD"
                    amountCzk={snap.total_cost_basis_czk}
                    secondaryMode="none"
                    size="lg"
                  />
                </KpiCard>

                {snap.living_draw_12m && (
                  <KpiCard
                    label="12m living draw"
                    content={<LivingDrawBreakdown draw={snap.living_draw_12m} />}
                  >
                    <Money
                      amount={snap.living_draw_12m.draw_usd}
                      currency="USD"
                      secondaryMode="none"
                      size="lg"
                      signed
                    />
                    <div className="text-[11px] text-ink-faint">
                      Sold {formatUsd(snap.living_draw_12m.sold_usd)} · reinvested{" "}
                      {formatUsd(snap.living_draw_12m.bought_usd)}
                    </div>
                  </KpiCard>
                )}
              </div>
              <p className="text-[11px] text-ink-faint">
                Hover or tap a KPI card for a breakdown · living draw = last 365d sell − buy cash
              </p>

              {(snap.fees || snap.staking) && (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-xs font-medium uppercase tracking-wide text-ink-faint">
                    Statement extras
                  </span>
                  {snap.fees && (
                    <span className="pill-warn">Fees {formatUsd(snap.fees.total_fees_usd)}</span>
                  )}
                  {snap.fees && (
                    <span className="pill-info">
                      Deposits {formatUsd(snap.fees.deposits_usd)}
                    </span>
                  )}
                  {snap.staking && (
                    <span className="pill-good">
                      Staking ≈ {formatUsd(snap.staking.mark_usd_total)}
                    </span>
                  )}
                  <Link
                    to="/investments/analysis"
                    className="text-[11px] font-medium text-brand hover:underline"
                  >
                    Full analysis →
                  </Link>
                </div>
              )}
            </>
          )}

          {snap && (
            <>
              <div
                ref={taxRunwayRef}
                className={cn(
                  "card scroll-mt-24 p-5",
                  focus === "tax_runway" && "ring-2 ring-brand/50",
                )}
              >
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-semibold">Tax-free runway</h2>
                  <span className="pill-good">
                    Available {formatUsd(snap.tax_runway.available_usd)}
                  </span>
                  <span className="pill-warn">
                    Still locked {formatUsd(snap.tax_runway.locked_usd)}
                  </span>
                </div>
                <p className="mb-4 text-xs text-ink-faint">
                  Hover any card for ticker split (market value when priced, else cost).
                </p>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {snap.tax_runway.buckets.map((b, i) => (
                    <HoverPanel
                      key={b.key}
                      content={
                        b.tickers.length === 0 ? (
                          <div className="text-xs text-ink-faint">No lots in this bucket</div>
                        ) : (
                          <ul className="space-y-1">
                            {b.tickers.map((t) => (
                              <li
                                key={t.ticker}
                                className="flex justify-between gap-3 text-xs"
                              >
                                <span>
                                  {t.ticker}{" "}
                                  <span className="text-ink-faint">
                                    ({formatQty(t.quantity)})
                                  </span>
                                </span>
                                <span className="font-medium">{formatUsd(t.amount_usd)}</span>
                              </li>
                            ))}
                          </ul>
                        )
                      }
                    >
                      <div
                        className={cn(
                          "rounded-xl border p-3 transition hover:border-brand/40",
                          i === 0 ? "border-ok/30 bg-ok/5" : "border-white/5 bg-white/[0.02]",
                        )}
                      >
                        <div className="label mb-1">{b.label}</div>
                        <Money
                          amount={b.amount_usd}
                          currency="USD"
                          secondaryMode="none"
                          size="lg"
                        />
                      </div>
                    </HoverPanel>
                  ))}
                </div>
              </div>
              <div
                ref={pricesRef}
                className={cn(
                  "scroll-mt-24",
                  focus === "prices" && "rounded-2xl ring-2 ring-brand/50",
                )}
              >
                <PriceStatusBanner snap={snap} />
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

type KpiBreakdown = {
  winners: Array<{ ticker: string; unrealized: number; cost: number; mv: number | null }>;
  losers: Array<{ ticker: string; unrealized: number; cost: number; mv: number | null }>;
  greenCount: number;
  pricedCount: number;
  byPlatformMv: Array<{ source: string; amount: number }>;
  byPlatformCost: Array<{ source: string; amount: number }>;
  topByMv: Array<{ ticker: string; mv: number; cost: number }>;
  topByCost: Array<{ ticker: string; cost: number; mv: number | null }>;
  realizedWinners: Array<{
    ticker: string;
    realized: number;
    cost: number | null;
    proceeds: number | null;
    roiPct: number | null;
  }>;
  realizedLosers: Array<{
    ticker: string;
    realized: number;
    cost: number | null;
    proceeds: number | null;
    roiPct: number | null;
  }>;
  realizedPositiveCount: number;
  realizedNegativeCount: number;
  totalMv: number | null;
  totalCost: number;
  unrealized: number | null;
};

function KpiCard({
  label,
  content,
  children,
}: {
  label: string;
  content: ReactNode;
  children: ReactNode;
}) {
  return (
    <HoverPanel
      className="card p-0"
      panelClassName="left-0 right-auto"
      content={content}
    >
      <div className="rounded-xl border border-transparent p-4 transition hover:border-brand/30">
        <div className="label mb-0.5">{label}</div>
        {children}
      </div>
    </HoverPanel>
  );
}

function BreakdownList({
  title,
  rows,
  valueClassName,
}: {
  title?: string;
  rows: Array<{ label: string; value: string; tone?: "ok" | "danger" | "muted" }>;
  valueClassName?: string;
}) {
  if (!rows.length) {
    if (!title) return null;
    return (
      <div className="mb-2 text-xs text-ink-faint">{title}: none</div>
    );
  }
  return (
    <div className="mb-2.5">
      {title ? (
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
          {title}
        </div>
      ) : null}
      <ul className="space-y-0.5">
        {rows.map((r) => (
          <li key={r.label} className="flex justify-between gap-3 text-xs">
            <span className="truncate text-ink-muted">{r.label}</span>
            <span
              className={cn(
                "shrink-0 font-medium tabular-nums",
                r.tone === "ok" && "text-ok",
                r.tone === "danger" && "text-danger",
                r.tone === "muted" && "text-ink-faint",
                valueClassName,
              )}
            >
              {r.value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Cost (muted) + gain (green) or loss (red) as share of market value. */
function InvestedGainBar({
  cost,
  market,
}: {
  cost: number;
  market: number;
}) {
  if (market <= 0 && cost <= 0) return null;
  const denom = Math.max(market, cost, 1);
  if (market >= cost) {
    const costPct = Math.min(100, (cost / denom) * 100);
    const gainPct = Math.min(100 - costPct, ((market - cost) / denom) * 100);
    return (
      <div
        className="mb-3 flex h-2 w-full overflow-hidden rounded-full bg-white/10"
        title="Invested (grey) + unrealized gain (green)"
      >
        <div className="bg-white/35" style={{ width: `${costPct}%` }} />
        <div className="bg-ok" style={{ width: `${gainPct}%` }} />
      </div>
    );
  }
  // Loss: market is green-ish remaining; loss segment in red of original cost
  const mvPct = Math.min(100, (market / denom) * 100);
  const lossPct = Math.min(100 - mvPct, ((cost - market) / denom) * 100);
  return (
    <div
      className="mb-3 flex h-2 w-full overflow-hidden rounded-full bg-white/10"
      title="Current value (grey) + unrealized loss (red)"
    >
      <div className="bg-white/35" style={{ width: `${mvPct}%` }} />
      <div className="bg-danger" style={{ width: `${lossPct}%` }} />
    </div>
  );
}

function SegmentBar({
  segments,
}: {
  segments: Array<{ amount: number; color: string; label: string }>;
}) {
  const total = segments.reduce((s, x) => s + Math.max(0, x.amount), 0);
  if (total <= 0) return null;
  return (
    <div className="mb-2 flex h-2 w-full overflow-hidden rounded-full bg-white/10">
      {segments.map((seg) => (
        <div
          key={seg.label}
          className={seg.color}
          style={{ width: `${(Math.max(0, seg.amount) / total) * 100}%` }}
          title={`${seg.label}: ${formatUsd(seg.amount)}`}
        />
      ))}
    </div>
  );
}

function signedUsd(n: number): string {
  const s = formatUsd(n);
  return n > 0 ? `+${s}` : s;
}

function UnrealizedBreakdown({
  snap,
  breakdown,
}: {
  snap: PortfolioSnapshot;
  breakdown: KpiBreakdown;
}) {
  if (breakdown.unrealized == null || breakdown.totalMv == null) {
    return (
      <p className="text-xs text-ink-faint">
        Update prices to see unrealized gain vs invested amount.
      </p>
    );
  }
  const pct = snap.unrealized_pct;
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        Unrealized gain
      </div>
      <InvestedGainBar cost={breakdown.totalCost} market={breakdown.totalMv} />
      <div className="mb-3 space-y-1.5">
        <div className="flex justify-between gap-3 text-xs">
          <span className="text-ink-muted">Unrealized gain</span>
          <span
            className={cn(
              "font-semibold tabular-nums",
              breakdown.unrealized >= 0 ? "text-ok" : "text-danger",
            )}
          >
            {signedUsd(breakdown.unrealized)}
            {pct != null ? ` (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)` : ""}
          </span>
        </div>
        <div className="flex justify-between gap-3 text-xs">
          <span className="text-ink-muted">Current portfolio value</span>
          <span className="font-medium tabular-nums">{formatUsd(breakdown.totalMv)}</span>
        </div>
        <div className="flex justify-between gap-3 text-xs">
          <span className="text-ink-muted">Invested amount</span>
          <span className="font-medium tabular-nums">{formatUsd(breakdown.totalCost)}</span>
        </div>
      </div>
      <BreakdownList
        title="Top winners"
        rows={breakdown.winners.slice(0, 5).map((w) => ({
          label: w.ticker,
          value: signedUsd(w.unrealized),
          tone: "ok" as const,
        }))}
      />
      {breakdown.losers.length > 0 && (
        <BreakdownList
          title="Top losers"
          rows={breakdown.losers.slice(0, 3).map((w) => ({
            label: w.ticker,
            value: signedUsd(w.unrealized),
            tone: "danger" as const,
          }))}
        />
      )}
      <p className="mt-1 text-[11px] text-ink-faint">
        {breakdown.greenCount} of {breakdown.pricedCount} priced tickers in the green
      </p>
    </div>
  );
}

function MarketValueBreakdown({
  snap,
  breakdown,
}: {
  snap: PortfolioSnapshot;
  breakdown: KpiBreakdown;
}) {
  const totalMv = breakdown.totalMv;
  const available = d(snap.tax_runway.available_usd);
  const locked = d(snap.tax_runway.locked_usd);
  return (
    <div>
      <BreakdownList
        title="Snapshot"
        rows={[
          {
            label: "Market value",
            value: totalMv != null ? formatUsd(totalMv) : "—",
          },
          { label: "Open cost", value: formatUsd(breakdown.totalCost) },
          {
            label: "Tickers",
            value: String(snap.ticker_count),
          },
          {
            label: "Prices as of",
            value: snap.prices_as_of || "—",
            tone: "muted" as const,
          },
        ]}
      />
      {breakdown.byPlatformMv.length > 0 && (
        <>
          <SegmentBar
            segments={breakdown.byPlatformMv.map((p, i) => ({
              amount: p.amount,
              label: p.source,
              color: i === 0 ? "bg-brand" : i === 1 ? "bg-violet-400" : "bg-amber-400",
            }))}
          />
          <BreakdownList
            title="By platform"
            rows={breakdown.byPlatformMv.map((p) => ({
              label: p.source,
              value:
                totalMv && totalMv > 0
                  ? `${formatUsd(p.amount)} (${((p.amount / totalMv) * 100).toFixed(0)}%)`
                  : formatUsd(p.amount),
            }))}
          />
        </>
      )}
      <BreakdownList
        title="Largest holdings"
        rows={breakdown.topByMv.slice(0, 5).map((t) => ({
          label: t.ticker,
          value:
            totalMv && totalMv > 0
              ? `${formatUsd(t.mv)} (${((t.mv / totalMv) * 100).toFixed(0)}%)`
              : formatUsd(t.mv),
        }))}
      />
      {(available > 0 || locked > 0) && (
        <>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
            Tax runway (MV)
          </div>
          <SegmentBar
            segments={[
              { amount: available, color: "bg-ok", label: "Tax-free now" },
              { amount: locked, color: "bg-warn", label: "Still locked" },
            ]}
          />
          <BreakdownList
            rows={[
              { label: "Tax-free now", value: formatUsd(available), tone: "ok" },
              { label: "Still locked", value: formatUsd(locked), tone: "muted" },
            ]}
          />
        </>
      )}
      {snap.missing_quotes.length > 0 && (
        <p className="text-[11px] text-warn">
          Missing quotes: {snap.missing_quotes.slice(0, 6).join(", ")}
          {snap.missing_quotes.length > 6 ? "…" : ""}
        </p>
      )}
    </div>
  );
}

function formatRealizedTickerValue(r: {
  realized: number;
  cost: number | null;
  roiPct: number | null;
}): string {
  const gain = signedUsd(r.realized);
  if (r.cost != null && r.cost > 0) {
    const roi =
      r.roiPct != null
        ? ` · ${r.roiPct >= 0 ? "+" : ""}${r.roiPct.toFixed(0)}%`
        : "";
    return `${gain} on ${formatUsd(r.cost)}${roi}`;
  }
  return gain;
}

function RealizedBreakdown({
  snap,
  breakdown,
}: {
  snap: PortfolioSnapshot;
  breakdown: KpiBreakdown;
}) {
  const total = d(snap.realized_lifetime_usd);
  const costSold =
    snap.realized_cost_basis_usd != null ? d(snap.realized_cost_basis_usd) : null;
  const proceeds =
    snap.realized_proceeds_usd != null ? d(snap.realized_proceeds_usd) : null;
  const roi = snap.realized_roi_pct;
  const lifetimeRows: Array<{
    label: string;
    value: string;
    tone?: "ok" | "danger" | "muted";
  }> = [
    {
      label: "Realized (FIFO)",
      value: signedUsd(total),
      tone: total >= 0 ? "ok" : "danger",
    },
  ];
  if (costSold != null && costSold > 0) {
    lifetimeRows.push({
      label: "Cost basis sold",
      value: formatUsd(costSold),
      tone: "muted",
    });
  }
  if (proceeds != null && proceeds > 0) {
    lifetimeRows.push({
      label: "Proceeds",
      value: formatUsd(proceeds),
      tone: "muted",
    });
  }
  if (roi != null) {
    lifetimeRows.push({
      label: "ROI on sold cost",
      value: `${roi >= 0 ? "+" : ""}${roi.toFixed(1)}%`,
      tone: roi >= 0 ? "ok" : "danger",
    });
  }
  lifetimeRows.push(
    {
      label: "Tickers with gains",
      value: String(breakdown.realizedPositiveCount),
    },
    {
      label: "Tickers with losses",
      value: String(breakdown.realizedNegativeCount),
    },
  );
  return (
    <div>
      <BreakdownList title="Lifetime" rows={lifetimeRows} />
      <BreakdownList
        title="Top closed winners"
        rows={breakdown.realizedWinners.slice(0, 5).map((r) => ({
          label: r.ticker,
          value: formatRealizedTickerValue(r),
          tone: "ok" as const,
        }))}
      />
      {breakdown.realizedLosers.length > 0 && (
        <BreakdownList
          title="Largest closed losses"
          rows={breakdown.realizedLosers.slice(0, 3).map((r) => ({
            label: r.ticker,
            value: formatRealizedTickerValue(r),
            tone: "danger" as const,
          }))}
        />
      )}
      <p className="mt-1 text-[11px] text-ink-faint">
        FIFO cost of closed lots · not open cost · open positions excluded from
        realized
      </p>
    </div>
  );
}

function CostBasisBreakdown({
  snap,
  breakdown,
}: {
  snap: PortfolioSnapshot;
  breakdown: KpiBreakdown;
}) {
  const totalCost = breakdown.totalCost;
  return (
    <div>
      <BreakdownList
        title="Capital at work"
        rows={[
          { label: "Open cost (USD)", value: formatUsd(snap.total_cost_basis_usd) },
          {
            label: "Open cost (CZK)",
            value: `${d(snap.total_cost_basis_czk).toLocaleString("cs-CZ")} Kč`,
          },
          {
            label: "Market value",
            value:
              breakdown.totalMv != null ? formatUsd(breakdown.totalMv) : "— (update prices)",
          },
          {
            label: "Unrealized vs cost",
            value:
              breakdown.unrealized != null
                ? `${signedUsd(breakdown.unrealized)}${
                    snap.unrealized_pct != null
                      ? ` (${snap.unrealized_pct >= 0 ? "+" : ""}${snap.unrealized_pct.toFixed(1)}%)`
                      : ""
                  }`
                : "—",
            tone:
              breakdown.unrealized == null
                ? "muted"
                : breakdown.unrealized >= 0
                  ? "ok"
                  : "danger",
          },
        ]}
      />
      {breakdown.byPlatformCost.length > 0 && (
        <>
          <SegmentBar
            segments={breakdown.byPlatformCost.map((p, i) => ({
              amount: p.amount,
              label: p.source,
              color: i === 0 ? "bg-brand" : i === 1 ? "bg-violet-400" : "bg-amber-400",
            }))}
          />
          <BreakdownList
            title="Cost by platform"
            rows={breakdown.byPlatformCost.map((p) => ({
              label: p.source,
              value:
                totalCost > 0
                  ? `${formatUsd(p.amount)} (${((p.amount / totalCost) * 100).toFixed(0)}%)`
                  : formatUsd(p.amount),
            }))}
          />
        </>
      )}
      <BreakdownList
        title="Largest cost concentrations"
        rows={breakdown.topByCost.slice(0, 5).map((t) => ({
          label: t.ticker,
          value:
            totalCost > 0
              ? `${formatUsd(t.cost)} (${((t.cost / totalCost) * 100).toFixed(0)}%)`
              : formatUsd(t.cost),
        }))}
      />
      <p className="mt-1 text-[11px] text-ink-faint">
        Tax runway below is marked at market value when priced
      </p>
    </div>
  );
}

function TickerDigestPanel({
  digest,
  copied,
  onCopy,
}: {
  digest: TickerDigest;
  copied: boolean;
  onCopy: () => void;
}) {
  const platformData = digest.by_platform.map((p, i) => ({
    name: p.source,
    quantity: d(p.quantity),
    fill: PLATFORM_COLORS[i % PLATFORM_COLORS.length],
  }));

  const trancheTotalMv = digest.tax_tranches.reduce(
    (s, t) => s + d(t.market_value_usd),
    0,
  );

  const gradeCls = GRADE_STYLE[digest.roi_grade] || GRADE_STYLE["—"];
  const growth = digest.growth_contribution_pp;
  const growthSign = growth != null && growth >= 0 ? "+" : "";

  return (
    <div className="space-y-5 rounded-xl border border-white/10 bg-black/20 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-xl font-bold tracking-tight">{digest.ticker}</h3>
            {digest.multi_platform && (
              <span className="badge bg-warn/15 text-warn">Multi-platform</span>
            )}
            {digest.missing_price && (
              <span className="badge bg-warn/15 text-warn">No price</span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span className="text-2xl font-semibold tabular-nums">
              {formatQty(digest.quantity_total)}
            </span>
            <span className="text-sm text-ink-faint">units owned</span>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md bg-white/5 px-2 py-0.5 text-[11px] text-ink-muted hover:bg-white/10 hover:text-ink"
              onClick={onCopy}
              title="Copy total quantity"
            >
              {copied ? <Check className="h-3 w-3 text-ok" /> : <Copy className="h-3 w-3" />}
              {copied ? "Copied" : "Copy qty"}
            </button>
          </div>
          <div className="mt-1 text-xs text-ink-faint">
            {digest.price_usd
              ? `Mark ${formatUsd(digest.price_usd)}${
                  digest.price_as_of ? ` · ${digest.price_as_of}` : ""
                }`
              : "No market quote yet — use Update prices in the header"}
            {" · "}
            Avg cost {formatUsd(digest.avg_cost_usd)}
          </div>
          {digest.missing_price && (
            <div className="mt-2 rounded-lg border border-warn/25 bg-warn/10 px-2.5 py-1.5 text-[11px] text-warn">
              ROI, growth contribution, and market value need a live quote. Cost basis is
              shown below until prices load.
            </div>
          )}
        </div>
        <div
          className={cn(
            "flex h-16 w-16 flex-col items-center justify-center rounded-2xl ring-1",
            gradeCls,
          )}
        >
          <span className="text-2xl font-bold leading-none">{digest.roi_grade}</span>
          <span className="mt-0.5 text-[10px] font-medium opacity-80">
            {digest.roi_grade_label}
          </span>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">
            Quantity by platform
          </h4>
          <div className="mb-2 h-36">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={platformData}
                layout="vertical"
                margin={{ top: 0, right: 12, left: 4, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#2e3a4d" horizontal={false} />
                <XAxis
                  type="number"
                  stroke="#6b7a90"
                  fontSize={11}
                  tickFormatter={(v: number) => formatQty(String(v))}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={72}
                  stroke="#6b7a90"
                  fontSize={11}
                />
                <Tooltip
                  contentStyle={{
                    background: "#1a2332",
                    border: "1px solid #2e3a4d",
                    borderRadius: 12,
                  }}
                  formatter={(v: number) => [formatQty(String(v)), "Qty"]}
                />
                <Bar dataKey="quantity" radius={[0, 6, 6, 0]} barSize={16}>
                  {platformData.map((e) => (
                    <Cell key={e.name} fill={e.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-ink-faint">
                <tr>
                  <th className="pb-1 font-medium">Platform</th>
                  <th className="pb-1 font-medium text-right">Qty</th>
                  <th className="pb-1 font-medium text-right">Cost</th>
                  <th className="pb-1 font-medium text-right">MV</th>
                  <th className="pb-1 font-medium text-right">Lots</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {digest.by_platform.map((p) => (
                  <tr key={p.source}>
                    <td className="py-1.5 font-medium">{p.source}</td>
                    <td className="py-1.5 text-right tabular-nums">
                      {formatQty(p.quantity)}
                    </td>
                    <td className="py-1.5 text-right tabular-nums">
                      {formatUsd(p.cost_basis_usd)}
                    </td>
                    <td className="py-1.5 text-right tabular-nums">
                      {formatUsd(p.market_value_usd)}
                    </td>
                    <td className="py-1.5 text-right text-ink-muted">{p.lot_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Market value by tax status
            </h4>
            {trancheTotalMv > 0 ? (
              <>
                <div className="flex h-8 w-full overflow-hidden rounded-lg ring-1 ring-white/10">
                  {digest.tax_tranches.map((t) => {
                    const mv = d(t.market_value_usd);
                    if (mv <= 0) return null;
                    const pct = (mv / trancheTotalMv) * 100;
                    return (
                      <div
                        key={t.key}
                        title={`${t.label}: ${formatUsd(t.market_value_usd)} · ${formatQty(t.quantity)} units`}
                        style={{
                          width: `${Math.max(pct, 1.5)}%`,
                          background: TAX_TRANCHE_COLORS[t.key] || "#64748b",
                        }}
                        className="h-full transition"
                      />
                    );
                  })}
                </div>
                <ul className="mt-2 space-y-1">
                  {digest.tax_tranches.map((t) => {
                    const mv = d(t.market_value_usd);
                    if (mv <= 0) return null;
                    return (
                      <li
                        key={t.key}
                        className="flex items-center justify-between gap-2 text-xs"
                      >
                        <span className="flex items-center gap-1.5 text-ink-muted">
                          <span
                            className="inline-block h-2 w-2 rounded-full"
                            style={{
                              background: TAX_TRANCHE_COLORS[t.key] || "#64748b",
                            }}
                          />
                          {t.label}
                          <span className="text-ink-faint">
                            ({formatQty(t.quantity)})
                          </span>
                        </span>
                        <span className="font-medium tabular-nums">
                          {formatUsd(t.market_value_usd)}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </>
            ) : (
              <p className="text-xs text-ink-faint">No market value for tax split.</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
              <div className="label mb-1">Unrealized</div>
              {digest.unrealized_usd != null ? (
                <>
                  <Money
                    amount={digest.unrealized_usd}
                    currency="USD"
                    secondaryMode="none"
                    size="lg"
                    signed
                  />
                  {digest.unrealized_pct != null && (
                    <div
                      className={cn(
                        "text-xs",
                        digest.unrealized_pct >= 0 ? "text-ok" : "text-danger",
                      )}
                    >
                      {digest.unrealized_pct >= 0 ? "+" : ""}
                      {digest.unrealized_pct.toFixed(1)}% ROI
                    </div>
                  )}
                </>
              ) : (
                <>
                  <span className="text-lg text-ink-faint">—</span>
                  <div className="text-[11px] text-ink-faint">Needs market quote</div>
                </>
              )}
            </div>
            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
              <div className="label mb-1">
                {digest.market_value_usd ? "Market value" : "Cost (no quote)"}
              </div>
              {digest.market_value_usd ? (
                <Money
                  amount={digest.market_value_usd}
                  currency="USD"
                  secondaryMode="none"
                  size="lg"
                />
              ) : (
                <Money
                  amount={digest.cost_basis_usd}
                  currency="USD"
                  secondaryMode="none"
                  size="lg"
                />
              )}
              <div className="text-xs text-ink-faint">
                Cost {formatUsd(digest.cost_basis_usd)}
              </div>
            </div>
            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
              <div className="label mb-1">Portfolio weight</div>
              <div className="text-xl font-semibold tabular-nums">
                {digest.portfolio_weight_pct.toFixed(1)}%
              </div>
              <div className="text-[11px] text-ink-faint">
                {digest.missing_price ? "of portfolio (cost mix)" : "of portfolio MV"}
              </div>
            </div>
            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
              <div className="label mb-1">Growth contribution</div>
              <div
                className={cn(
                  "text-xl font-semibold tabular-nums",
                  growth != null && growth >= 0
                    ? "text-ok"
                    : growth != null
                      ? "text-danger"
                      : "text-ink-faint",
                )}
              >
                {growth == null ? "—" : `${growthSign}${growth.toFixed(1)} pp`}
              </div>
              <div className="text-[11px] text-ink-faint">
                {growth == null ? "Needs market quote" : "of portfolio return"}
              </div>
            </div>
          </div>

          <p className="text-xs leading-relaxed text-ink-muted">
            {growth != null ? (
              <>
                Adds{" "}
                <span className="font-medium text-ink">
                  {growthSign}
                  {growth.toFixed(1)}pp
                </span>{" "}
                to portfolio return · {digest.portfolio_weight_pct.toFixed(1)}% of MV
                {digest.unrealized_share_pct != null && (
                  <>
                    {" "}
                    · {digest.unrealized_share_pct.toFixed(0)}% of total unrealized P&amp;L
                  </>
                )}
                .
              </>
            ) : (
              <>
                Weight {digest.portfolio_weight_pct.toFixed(1)}% of portfolio (cost basis when
                unpriced).
              </>
            )}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-white/5 pt-3 text-[11px] text-ink-faint">
        <span>
          Open lots: <span className="text-ink-muted">{digest.open_lot_count}</span>
        </span>
        {digest.first_acquired && (
          <span>
            First: <span className="text-ink-muted">{digest.first_acquired}</span>
          </span>
        )}
        {digest.last_acquired && (
          <span>
            Last: <span className="text-ink-muted">{digest.last_acquired}</span>
          </span>
        )}
        {digest.next_unlock_date ? (
          <span>
            Next unlock:{" "}
            <span className="text-warn">
              {digest.next_unlock_date}
              {digest.next_unlock_quantity
                ? ` (${formatQty(digest.next_unlock_quantity)})`
                : ""}
            </span>
          </span>
        ) : (
          <span className="text-ok">All open qty tax-eligible</span>
        )}
        <span>
          Realized lifetime:{" "}
          <span className="text-ink-muted">
            {formatUsd(digest.realized_lifetime_usd)}
            {digest.realized_cost_basis_usd != null &&
              d(digest.realized_cost_basis_usd) > 0 && (
                <>
                  {" "}
                  on {formatUsd(digest.realized_cost_basis_usd)} sold
                  {digest.realized_roi_pct != null && (
                    <>
                      {" "}
                      (
                      {digest.realized_roi_pct >= 0 ? "+" : ""}
                      {digest.realized_roi_pct.toFixed(0)}%)
                    </>
                  )}
                </>
              )}
          </span>
        </span>
      </div>
    </div>
  );
}

function PriceStatusBanner({ snap }: { snap: PortfolioSnapshot }) {
  const ps = snap.price_status;
  const mode = ps?.mode || (snap.missing_quotes.length ? "partial" : snap.prices_as_of ? "live_ok" : "empty");
  const note =
    ps?.note ||
    (snap.prices_as_of
      ? `Price data · ${snap.quote_count} quotes · as of ${snap.prices_as_of}`
      : "No prices loaded");
  return (
    <div
      className={cn(
        "rounded-xl border px-4 py-3 text-sm",
        mode === "empty" || mode === "stale"
          ? "border-warn/30 bg-warn/10 text-warn"
          : mode === "partial"
            ? "border-warn/30 bg-warn/10 text-warn"
            : "border-brand/30 bg-brand/10 text-brand",
      )}
    >
      <div>{note}</div>
      {ps?.mode_note && (
        <div className="mt-1 text-[11px] opacity-80">{ps.mode_note}</div>
      )}
      {(snap.missing_quotes.length > 0 || mode === "empty") && (
        <div className="mt-1 text-[11px] opacity-90">
          Use <strong>Update prices</strong> in the header for live marks.
        </div>
      )}
    </div>
  );
}

function LivingDrawBreakdown({ draw }: { draw: LivingDraw12m }) {
  const drawN = d(draw.draw_usd);
  return (
    <div>
      <BreakdownList
        title={`${draw.window_start} → ${draw.window_end}`}
        rows={[
          {
            label: "Sold (cash in)",
            value: formatUsd(draw.sold_usd),
            tone: "ok",
          },
          {
            label: "Reinvested (buys)",
            value: formatUsd(draw.bought_usd),
          },
          {
            label: "Net living draw",
            value: signedUsd(drawN),
            tone: drawN >= 0 ? "muted" : "ok",
          },
        ]}
      />
      <BreakdownList
        title="By ticker"
        rows={draw.by_ticker.slice(0, 8).map((r) => {
          const net = d(r.draw_usd);
          return {
            label: r.ticker,
            value: signedUsd(net),
            tone: (net >= 0 ? "muted" : "ok") as "ok" | "danger" | "muted",
          };
        })}
      />
      <p className="mt-1 text-[11px] text-ink-faint">
        Buy/Sell value_usd only · staking & fees excluded · Revolut fee-net is units, not this cash
      </p>
    </div>
  );
}

// Re-export analysis widgets (split modules)
export {
  InvestmentsSubNav,
  HealthBand,
  CashflowMonthlyChart,
  FeesBreakdownSection,
  StakingRewardsSection,
} from "../features/investments";
