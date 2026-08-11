import { Link } from "react-router-dom";
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import type { PortfolioSnapshot } from "../../api/types";
import { Money } from "../../components/Money";
import { formatUsd } from "../../lib/money";
import { cn } from "../../lib/cn";
import { gradeStyleClass } from "../investments/gradeStyles";
import {
  HoldingsWealthBand,
  type KpiBreakdown,
} from "../investments/HoldingsWealthBand";
import { TaxRunwayCard } from "../investments/TaxRunwayCard";
import type { AlertBucketCounts } from "./alertBuckets";
import { d } from "../../lib/money";

/**
 * Home executive hero: portfolio desk block (from Holdings) + cash dial + alert counts.
 */
export function ExecutiveHero({
  snap,
  breakdown,
  wealthRefreshing,
  cashLabel,
  netCashflow,
  netCzk,
  netChangePct,
  canGoNext,
  onShiftMonth,
  alertBuckets,
}: {
  snap: PortfolioSnapshot;
  breakdown?: KpiBreakdown | null;
  wealthRefreshing?: boolean;
  cashLabel: string;
  netCashflow: string | number;
  netCzk?: string | null;
  netChangePct?: number | null;
  canGoNext: boolean;
  onShiftMonth: (delta: number) => void;
  alertBuckets: AlertBucketCounts;
}) {
  const health = snap.health;
  const grade = health?.grade ?? "—";
  const conc = health?.concentration;
  const priceNote = snap.price_status?.note;
  const mode = snap.price_status?.mode;
  const netN = typeof netCashflow === "number" ? netCashflow : d(netCashflow);
  const netPositive = netN >= 0;

  return (
    <section
      className="relative overflow-hidden rounded-2xl border p-5 sm:p-6"
      style={{
        background:
          "linear-gradient(135deg, rgba(59,130,246,0.16), rgba(16,185,129,0.10) 45%, rgba(15,23,42,0.85))",
        borderColor: "rgba(52,211,153,0.35)",
        boxShadow: "0 20px 50px rgba(0,0,0,0.35)",
      }}
    >
      <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-brand/10 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-20 left-1/3 h-40 w-40 rounded-full bg-ok/10 blur-3xl" />

      <div className="relative space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
            Executive snapshot
            {wealthRefreshing && (
              <span className="ml-2 font-medium normal-case tracking-normal text-brand">
                Refreshing prices…
              </span>
            )}
          </div>
          <Link
            to="/investments"
            className="inline-flex items-center gap-0.5 text-[11px] font-medium text-brand hover:underline"
          >
            Holdings <ArrowRight className="h-3 w-3" />
          </Link>
        </div>

        {/* Top row: portfolio summary + cash dial */}
        <div className="grid gap-6 lg:grid-cols-2 lg:gap-8">
          <div className="flex min-w-0 flex-wrap items-start gap-4">
            {health && (
              <div
                className={cn(
                  "flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-2xl ring-1",
                  gradeStyleClass(grade),
                )}
              >
                <span className="text-2xl font-bold leading-none">{health.grade}</span>
                <span className="text-[10px] opacity-80">{health.score}/100</span>
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-ok">
                Portfolio
              </div>
              <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                {snap.total_market_value_usd ? (
                  <div className="text-2xl font-bold tracking-tight sm:text-3xl">
                    <Money
                      amount={snap.total_market_value_usd}
                      currency="USD"
                      secondaryMode="hover"
                      size="lg"
                    />
                  </div>
                ) : (
                  <span className="text-2xl font-bold text-ink-faint">Update prices</span>
                )}
                {snap.unrealized_pct != null && (
                  <span
                    className={cn(
                      "text-sm font-semibold tabular-nums",
                      snap.unrealized_pct >= 0 ? "text-ok" : "text-danger",
                    )}
                  >
                    {snap.unrealized_pct >= 0 ? "+" : ""}
                    {snap.unrealized_pct.toFixed(1)}% open
                  </span>
                )}
              </div>
              {health?.summary && (
                <p className="mt-1 max-w-xl text-sm text-ink-muted">{health.summary}</p>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <span className="text-ink-faint">As of {snap.as_of}</span>
                {conc && (
                  <span className="text-ink-faint">
                    · Top {conc.top_ticker ?? "—"}{" "}
                    {conc.top_weight_pct != null
                      ? `${conc.top_weight_pct.toFixed(0)}%`
                      : ""}
                  </span>
                )}
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[11px] font-medium",
                    mode === "live_ok"
                      ? "bg-ok/15 text-ok"
                      : mode === "partial" || mode === "stale" || mode === "empty"
                        ? "bg-warn/15 text-warn"
                        : "bg-white/5 text-ink-muted",
                  )}
                  title={priceNote}
                >
                  {mode === "live_ok"
                    ? "Prices live"
                    : mode === "partial"
                      ? "Prices partial"
                      : mode === "stale"
                        ? "Prices stale"
                        : mode === "empty"
                          ? "No prices"
                          : "Prices"}
                </span>
                <span className="pill-good">
                  Tax-free now {formatUsd(snap.tax_free_now_usd)}
                </span>
              </div>
            </div>
          </div>

          {/* Cash dial (from former dashboard hero) */}
          <div className="min-w-0 border-t border-white/10 pt-5 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-brand">
                Cash
              </span>
              <div className="flex items-center gap-0.5 rounded-lg border border-white/10 bg-black/20 p-0.5">
                <button
                  type="button"
                  aria-label="Previous month"
                  className="rounded-md p-1 text-ink-muted transition hover:bg-white/10 hover:text-ink"
                  onClick={() => onShiftMonth(-1)}
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="min-w-[7.5rem] px-1 text-center text-xs font-semibold tabular-nums text-ink">
                  {cashLabel}
                </span>
                <button
                  type="button"
                  aria-label="Next month"
                  disabled={!canGoNext}
                  className={cn(
                    "rounded-md p-1 transition",
                    canGoNext
                      ? "text-ink-muted hover:bg-white/10 hover:text-ink"
                      : "cursor-not-allowed text-ink-faint opacity-40",
                  )}
                  onClick={() => onShiftMonth(1)}
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
              <Link
                to="/expenses/spending"
                className="ml-auto inline-flex items-center gap-0.5 text-[11px] font-medium text-brand hover:underline"
              >
                Spending <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            <div className="flex items-baseline gap-2">
              <div
                className={cn(
                  "text-2xl font-bold tracking-tight sm:text-3xl",
                  netPositive ? "text-ok" : "text-danger",
                )}
              >
                <Money
                  amount={netCashflow}
                  currency="USD"
                  amountCzk={netCzk ?? undefined}
                  secondaryMode="hover"
                  size="lg"
                  signed
                />
              </div>
              {netPositive ? (
                <TrendingUp className="h-5 w-5 shrink-0 text-ok opacity-80" />
              ) : (
                <TrendingDown className="h-5 w-5 shrink-0 text-danger opacity-80" />
              )}
            </div>
            <div className="mt-1 text-sm text-ink-muted">
              Net cashflow this period
              {netChangePct != null && (
                <span
                  className={cn(
                    "ml-2 font-medium tabular-nums",
                    netChangePct >= 0 ? "text-ok" : "text-danger",
                  )}
                >
                  vs prior {netChangePct >= 0 ? "+" : ""}
                  {netChangePct.toFixed(0)}%
                </span>
              )}
            </div>
          </div>
        </div>

        {(snap.fees || snap.staking) && (
          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            {snap.fees && (
              <span className="pill-warn">
                Fees {formatUsd(snap.fees.total_fees_usd)}
              </span>
            )}
            {snap.staking && (
              <span className="pill-good">
                Staking ≈ {formatUsd(snap.staking.mark_usd_total)}
              </span>
            )}
            <Link
              to="/investments/analysis"
              className="font-medium text-brand hover:underline"
            >
              Full analysis →
            </Link>
          </div>
        )}

        {breakdown && (
          <div className="border-t border-white/10 pt-4">
            <HoldingsWealthBand snap={snap} breakdown={breakdown} embedded />
          </div>
        )}

        {snap.tax_runway?.buckets?.length > 0 && (
          <div className="border-t border-white/10 pt-4">
            <TaxRunwayCard snap={snap} embedded />
          </div>
        )}

        {/* Alert counts last — after wealth + tax runway */}
        <div className="border-t border-white/10 pt-4">
          <AlertCountStrip buckets={alertBuckets} />
        </div>
      </div>
    </section>
  );
}

function AlertCountStrip({ buckets }: { buckets: AlertBucketCounts }) {
  const chips: Array<{ key: string; label: string; count: number }> = [
    { key: "spending", label: "Spending", count: buckets.spending },
    { key: "stocks", label: "Stocks", count: buckets.stocks },
    { key: "crypto", label: "Crypto", count: buckets.crypto },
  ];

  return (
    <Link
      to="/expenses/alerts"
      className="flex flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-black/20 px-3 py-2.5 transition hover:border-brand/40"
      title="Open all alerts"
    >
      <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        Alerts
      </span>
      {chips.map((c) => (
        <span
          key={c.key}
          className={cn(
            "inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium tabular-nums",
            c.count > 0
              ? "bg-warn/15 text-warn ring-1 ring-warn/30"
              : "bg-white/5 text-ink-faint",
          )}
        >
          {c.label}
          <span className="font-bold">{c.count}</span>
        </span>
      ))}
      <span className="ml-auto inline-flex items-center gap-0.5 text-[11px] font-medium text-brand">
        View all
        {buckets.total > 0 ? ` (${buckets.total})` : ""}
        <ArrowRight className="h-3 w-3" />
      </span>
    </Link>
  );
}
