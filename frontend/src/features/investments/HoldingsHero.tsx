import { Link } from "react-router-dom";
import type { PortfolioSnapshot } from "../../api/types";
import { Money } from "../../components/Money";
import { formatUsd } from "../../lib/money";
import { cn } from "../../lib/cn";
import { gradeStyleClass } from "./gradeStyles";
import { HoldingsWealthBand, type KpiBreakdown } from "./HoldingsWealthBand";
import { TaxRunwayCard } from "./TaxRunwayCard";

/**
 * Bottom desk summary: portfolio grade/MV + embedded wealth KPIs + tax-free runway.
 */
export function HoldingsHero({
  snap,
  breakdown,
  focus,
  runwayRef,
}: {
  snap: PortfolioSnapshot;
  breakdown?: KpiBreakdown | null;
  focus?: string;
  runwayRef?: React.Ref<HTMLDivElement>;
}) {
  const health = snap.health;
  const grade = health?.grade ?? "—";
  const conc = health?.concentration;
  const priceNote = snap.price_status?.note;
  const mode = snap.price_status?.mode;

  return (
    <section
      className="relative rounded-2xl border p-5 sm:p-6"
      style={{
        background:
          "linear-gradient(135deg, rgba(59,130,246,0.16), rgba(16,185,129,0.10) 45%, rgba(15,23,42,0.85))",
        borderColor: "rgba(52,211,153,0.35)",
        boxShadow: "0 20px 50px rgba(0,0,0,0.35)",
      }}
    >
      {/* Clip glow orbs to the card; do not clip HoverPanel popups (wealth KPIs, tax runway). */}
      <div
        className="pointer-events-none absolute inset-0 overflow-hidden rounded-2xl"
        aria-hidden
      >
        <div className="absolute -right-16 -top-16 h-48 w-48 rounded-full bg-brand/10 blur-3xl" />
        <div className="absolute -bottom-20 left-1/3 h-40 w-40 rounded-full bg-ok/10 blur-3xl" />
      </div>

      <div className="relative space-y-5">
        <div className="flex flex-wrap items-start gap-4">
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
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
              Portfolio desk
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
                <span className="text-2xl font-bold text-ink-faint">Awaiting quotes</span>
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
              <p className="mt-1 max-w-2xl text-sm text-ink-muted">{health.summary}</p>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <span className="text-ink-faint">As of {snap.as_of}</span>
              {conc && (
                <span className="text-ink-faint">
                  · Top {conc.top_ticker ?? "—"}{" "}
                  {conc.top_weight_pct != null ? `${conc.top_weight_pct.toFixed(0)}%` : ""}
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

          {(snap.fees || snap.staking) && (
            <div className="flex flex-col items-end gap-1.5 text-right">
              {snap.fees && (
                <span className="pill-warn text-[11px]">
                  Fees {formatUsd(snap.fees.total_fees_usd)}
                </span>
              )}
              {snap.staking && (
                <span className="pill-good text-[11px]">
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
        </div>

        {breakdown && (
          <div className="border-t border-white/10 pt-4">
            <HoldingsWealthBand snap={snap} breakdown={breakdown} embedded />
          </div>
        )}

        {snap.tax_runway?.buckets?.length > 0 && (
          <div className="border-t border-white/10 pt-4">
            <TaxRunwayCard
              snap={snap}
              focus={focus}
              runwayRef={runwayRef}
              embedded
            />
          </div>
        )}
      </div>
    </section>
  );
}
