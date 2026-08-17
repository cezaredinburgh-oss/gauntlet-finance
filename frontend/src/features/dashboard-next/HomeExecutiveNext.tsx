import { Link } from "react-router-dom";
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import type { DashboardSummary, PortfolioSnapshot } from "../../api/types";
import { Money } from "../../components/Money";
import { d, formatUsd } from "../../lib/money";
import { cn } from "../../lib/cn";
import { homeWorkChips } from "./homeWorkChips";

export function HomeExecutiveNext({
  dash,
  snap,
  wealthRefreshing,
  cashLabel,
  netCashflow,
  netCzk,
  netChangePct,
  canGoNext,
  onShiftMonth,
}: {
  dash: DashboardSummary;
  snap: PortfolioSnapshot | null;
  wealthRefreshing?: boolean;
  cashLabel: string;
  netCashflow: string | number;
  netCzk?: string | null;
  netChangePct?: number | null;
  canGoNext: boolean;
  onShiftMonth: (delta: number) => void;
}) {
  const priceNote = snap?.price_status?.note;
  const mode = snap?.price_status?.mode;
  const netN = typeof netCashflow === "number" ? netCashflow : d(netCashflow);
  const netPositive = netN >= 0;
  const chips = homeWorkChips(dash);

  return (
    <section
      className="relative min-w-0 rounded-2xl border p-5 sm:p-6"
      style={{
        background:
          "linear-gradient(135deg, rgba(59,130,246,0.16), rgba(16,185,129,0.10) 45%, rgba(15,23,42,0.85))",
        borderColor: "rgba(52,211,153,0.35)",
        boxShadow: "0 20px 50px rgba(0,0,0,0.35)",
      }}
    >
      <div
        className="pointer-events-none absolute inset-0 overflow-hidden rounded-2xl"
        aria-hidden
      >
        <div className="absolute -right-16 -top-16 h-48 w-48 rounded-full bg-brand/10 blur-3xl" />
        <div className="absolute -bottom-20 left-1/3 h-40 w-40 rounded-full bg-ok/10 blur-3xl" />
      </div>

      <div className="relative space-y-5">
        {wealthRefreshing && (
          <div className="min-w-0 max-w-full text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
            <span className="inline-flex items-center gap-1.5 font-medium normal-case tracking-normal text-brand">
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-brand/30 border-t-brand" />
              Working — refreshing prices (~12s)
            </span>
          </div>
        )}

        <div className="grid min-w-0 gap-6 lg:grid-cols-2 lg:gap-8">
          <div className="min-w-0 max-w-full">
            {snap ? (
              <>
                <div className="text-[11px] font-semibold uppercase tracking-wide text-ok">
                  Portfolio
                </div>
                <div className="mt-1 flex min-w-0 max-w-full flex-wrap items-baseline gap-x-3 gap-y-1">
                  {snap.total_market_value_usd ? (
                    <div className="min-w-0 text-2xl font-bold tracking-tight sm:text-3xl">
                      <Money
                        amount={snap.total_market_value_usd}
                        currency="USD"
                        secondaryMode="hover"
                        size="lg"
                      />
                    </div>
                  ) : (
                    <span className="text-2xl font-bold text-ink-faint">
                      Awaiting quotes
                    </span>
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
                {snap.missing_quotes.length > 0 && (
                  <p className="mt-1 min-w-0 max-w-full text-xs text-warn">
                    Marked MV only · {snap.missing_quotes.length} unpriced
                    {snap.missing_quotes.length <= 4
                      ? ` (${snap.missing_quotes.join(", ")})`
                      : ""}
                  </p>
                )}
                <div className="mt-2 flex min-w-0 max-w-full flex-wrap items-center gap-2 text-xs">
                  <span className="text-ink-faint">As of {snap.as_of}</span>
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
                  <Link
                    to="/investments"
                    className="inline-flex items-center gap-0.5 text-[11px] font-medium text-brand hover:underline"
                  >
                    Holdings <ArrowRight className="h-3 w-3" />
                  </Link>
                </div>
              </>
            ) : (
              <p className="min-w-0 max-w-full text-sm text-ink-muted">
                Portfolio snapshot unavailable
              </p>
            )}
          </div>

          <div className="min-w-0 max-w-full border-t border-white/10 pt-5 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
            <div className="mb-2 flex min-w-0 max-w-full flex-wrap items-center gap-2">
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
            <div className="flex min-w-0 max-w-full flex-wrap items-baseline gap-2">
              <div
                className={cn(
                  "min-w-0 text-2xl font-bold tracking-tight sm:text-3xl",
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
            <div className="mt-1 min-w-0 max-w-full text-sm text-ink-muted">
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

        {chips.length > 0 && (
          <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
            {chips.map((chip) => (
              <Link
                key={chip.key}
                to={chip.to}
                title={
                  chip.key === "uncategorized"
                    ? formatUsd(dash.spending.uncategorized_expense_usd)
                    : undefined
                }
                className="inline-flex min-w-0 max-w-full items-center rounded-lg border border-white/10 bg-black/20 px-2.5 py-1 text-xs font-medium text-ink transition hover:border-brand/40"
              >
                {chip.label}
              </Link>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
