import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ChevronLeft, ChevronRight, TrendingDown, TrendingUp } from "lucide-react";
import { Money } from "../../components/Money";
import { gradeStyleClass } from "../investments/gradeStyles";
import { cn } from "../../lib/cn";

export function HomeHero({
  asOf,
  cashLabel,
  priceNote,
  wealthRefreshing,
  grade,
  healthScore,
  healthSummary,
  marketValueUsd,
  unrealizedPct,
  netCashflow,
  netCzk,
  netChangePct,
  canGoNext,
  onShiftMonth,
}: {
  asOf: string;
  cashLabel: string;
  priceNote?: string | null;
  wealthRefreshing?: boolean;
  grade: string;
  healthScore?: number | null;
  healthSummary?: string | null;
  marketValueUsd: string | null | undefined;
  unrealizedPct?: number | null;
  netCashflow: string | number;
  netCzk?: string | null;
  netChangePct?: number | null;
  canGoNext: boolean;
  onShiftMonth: (delta: number) => void;
}) {
  const netN =
    typeof netCashflow === "number" ? netCashflow : Number(String(netCashflow).replace(/,/g, ""));
  const netPositive = !Number.isNaN(netN) ? netN >= 0 : true;

  return (
    <section
      className="relative overflow-hidden rounded-2xl border p-5 sm:p-7"
      style={{
        background:
          "linear-gradient(135deg, rgba(59,130,246,0.16), rgba(16,185,129,0.10) 45%, rgba(15,23,42,0.85))",
        borderColor: "rgba(52,211,153,0.35)",
        boxShadow: "0 20px 50px rgba(0,0,0,0.35)",
      }}
    >
      <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-brand/10 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-20 left-1/3 h-40 w-40 rounded-full bg-ok/10 blur-3xl" />

      <div className="relative">
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
          Executive snapshot
          {wealthRefreshing && (
            <span className="ml-2 font-medium normal-case tracking-normal text-brand">
              Refreshing prices…
            </span>
          )}
        </div>

        <div className="mt-4 grid gap-6 lg:grid-cols-2 lg:gap-8">
          {/* Wealth dial */}
          <div className="min-w-0">
            <div className="mb-2 flex items-center gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-ok">
                Portfolio
              </span>
              <span
                className={cn(
                  "inline-flex h-7 min-w-[1.75rem] items-center justify-center rounded-lg px-1.5 text-xs font-bold ring-1",
                  gradeStyleClass(grade),
                )}
                title={healthSummary || "Portfolio health grade"}
              >
                {grade}
                {healthScore != null ? (
                  <span className="ml-0.5 text-[10px] font-semibold opacity-80">
                    {healthScore}
                  </span>
                ) : null}
              </span>
              <Link
                to="/investments"
                className="ml-auto inline-flex items-center gap-0.5 text-[11px] font-medium text-brand hover:underline"
              >
                Holdings <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            {marketValueUsd ? (
              <div className="text-3xl font-bold tracking-tight sm:text-4xl">
                <Money
                  amount={marketValueUsd}
                  currency="USD"
                  secondaryMode="hover"
                  size="lg"
                />
              </div>
            ) : (
              <div className="text-2xl font-bold text-ink-faint sm:text-3xl">
                Awaiting quotes
              </div>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              {unrealizedPct != null && (
                <span
                  className={cn(
                    "font-semibold tabular-nums",
                    unrealizedPct >= 0 ? "text-ok" : "text-danger",
                  )}
                >
                  {unrealizedPct >= 0 ? "+" : ""}
                  {unrealizedPct.toFixed(1)}% open
                </span>
              )}
              {healthSummary && (
                <span className="text-ink-muted line-clamp-2">{healthSummary}</span>
              )}
            </div>
          </div>

          {/* Cash dial */}
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
                  "text-3xl font-bold tracking-tight sm:text-4xl",
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

        <p className="mt-5 text-[11px] leading-relaxed text-ink-faint">
          Portfolio as of {asOf}
          {priceNote ? ` · ${priceNote}` : ""}
          {" · "}
          Cash: {cashLabel}
          {" · "}
          Draw: trailing 12m investment cash
        </p>
      </div>
    </section>
  );
}

export function HomeDeepLinks({ children }: { children?: ReactNode }) {
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      {children ?? (
        <>
          <DeepLink to="/investments" label="Holdings" />
          <DeepLink to="/investments/analysis" label="Analysis" />
          <DeepLink to="/investments/tax" label="Tax" />
          <DeepLink to="/expenses/spending" label="Spending" />
        </>
      )}
    </div>
  );
}

function DeepLink({ to, label }: { to: string; label: string }) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-1 rounded-full border border-slate-500/25 bg-surface-raised/60 px-3 py-1.5 font-medium text-ink-muted transition hover:border-brand/40 hover:text-brand"
    >
      {label}
      <ArrowRight className="h-3 w-3" />
    </Link>
  );
}
