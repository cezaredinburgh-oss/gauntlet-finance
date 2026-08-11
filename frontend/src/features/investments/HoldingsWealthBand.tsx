import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, LineChart, TrendingDown, TrendingUp, Wallet } from "lucide-react";
import type { LivingDraw12m, PortfolioSnapshot, TickerDigest } from "../../api/types";
import { Money } from "../../components/Money";
import { HoverPanel } from "../../components/HoverPanel";
import { d, formatUsd } from "../../lib/money";
import { cn } from "../../lib/cn";

export type KpiBreakdown = {
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

export function buildKpiBreakdown(
  snap: PortfolioSnapshot,
  digests: TickerDigest[],
): KpiBreakdown {
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
    totalMv: snap.total_market_value_usd != null ? d(snap.total_market_value_usd) : null,
    totalCost: d(snap.total_cost_basis_usd),
    unrealized: snap.unrealized_usd != null ? d(snap.unrealized_usd) : null,
  };
}

function signedUsd(n: number): string {
  const s = formatUsd(n);
  return n > 0 ? `+${s}` : s;
}

function BreakdownList({
  title,
  rows,
}: {
  title?: string;
  rows: Array<{ label: string; value: string; tone?: "ok" | "danger" | "muted" }>;
}) {
  if (!rows.length) {
    if (!title) return null;
    return <div className="mb-2 text-xs text-ink-faint">{title}: none</div>;
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

function InvestedGainBar({ cost, market }: { cost: number; market: number }) {
  if (market <= 0 && cost <= 0) return null;
  const denom = Math.max(market, cost, 1);
  if (market >= cost) {
    const costPct = Math.min(100, (cost / denom) * 100);
    const gainPct = Math.min(100 - costPct, ((market - cost) / denom) * 100);
    return (
      <div className="mb-3 flex h-2 w-full overflow-hidden rounded-full bg-white/10">
        <div className="bg-white/35" style={{ width: `${costPct}%` }} />
        <div className="bg-ok" style={{ width: `${gainPct}%` }} />
      </div>
    );
  }
  const mvPct = Math.min(100, (market / denom) * 100);
  const lossPct = Math.min(100 - mvPct, ((cost - market) / denom) * 100);
  return (
    <div className="mb-3 flex h-2 w-full overflow-hidden rounded-full bg-white/10">
      <div className="bg-white/35" style={{ width: `${mvPct}%` }} />
      <div className="bg-danger" style={{ width: `${lossPct}%` }} />
    </div>
  );
}

function ExecStat({
  label,
  icon,
  content,
  children,
  footer,
}: {
  label: string;
  icon?: ReactNode;
  content: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <HoverPanel
      className="rounded-xl border border-white/10 bg-black/20 p-0"
      panelClassName="left-0 right-auto"
      content={content}
    >
      <div className="p-3 transition hover:border-brand/40">
        <div className="mb-1 flex items-center gap-1.5">
          {icon}
          <div className="label mb-0">{label}</div>
        </div>
        {children}
        {footer}
      </div>
    </HoverPanel>
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
          { label: "Market value", value: totalMv != null ? formatUsd(totalMv) : "—" },
          { label: "Open cost", value: formatUsd(breakdown.totalCost) },
          { label: "Tickers", value: String(snap.ticker_count) },
          {
            label: "Prices as of",
            value: snap.prices_as_of || "—",
            tone: "muted",
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
        </>
      )}
    </div>
  );
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
      </div>
      <BreakdownList
        title="Top winners"
        rows={breakdown.winners.slice(0, 5).map((w) => ({
          label: w.ticker,
          value: signedUsd(w.unrealized),
          tone: "ok",
        }))}
      />
      {breakdown.losers.length > 0 && (
        <BreakdownList
          title="Top losers"
          rows={breakdown.losers.slice(0, 3).map((w) => ({
            label: w.ticker,
            value: signedUsd(w.unrealized),
            tone: "danger",
          }))}
        />
      )}
      <p className="mt-1 text-[11px] text-ink-faint">
        {breakdown.greenCount} of {breakdown.pricedCount} priced tickers in the green
      </p>
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
  if (roi != null) {
    lifetimeRows.push({
      label: "ROI on sold cost",
      value: `${roi >= 0 ? "+" : ""}${roi.toFixed(1)}%`,
      tone: roi >= 0 ? "ok" : "danger",
    });
  }
  return (
    <div>
      <BreakdownList title="Lifetime" rows={lifetimeRows} />
      <BreakdownList
        title="Top closed winners"
        rows={breakdown.realizedWinners.slice(0, 5).map((r) => ({
          label: r.ticker,
          value: formatRealizedTickerValue(r),
          tone: "ok",
        }))}
      />
      {breakdown.realizedLosers.length > 0 && (
        <BreakdownList
          title="Largest closed losses"
          rows={breakdown.realizedLosers.slice(0, 3).map((r) => ({
            label: r.ticker,
            value: formatRealizedTickerValue(r),
            tone: "danger",
          }))}
        />
      )}
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
        ]}
      />
      {breakdown.byPlatformCost.length > 0 && (
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
          { label: "Sold (cash in)", value: formatUsd(draw.sold_usd), tone: "ok" },
          { label: "Reinvested (buys)", value: formatUsd(draw.bought_usd) },
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
      <p className="mt-2 text-[11px]">
        <Link to="/investments/analysis" className="font-medium text-brand hover:underline">
          Full draw vs safe capacity →
        </Link>
      </p>
    </div>
  );
}

/** Nested wealth KPIs (Dashboard ExecStat grammar). */
export function HoldingsWealthBand({
  snap,
  breakdown,
}: {
  snap: PortfolioSnapshot;
  breakdown: KpiBreakdown;
}) {
  return (
    <section className="card p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold tracking-wide text-brand">Wealth</h2>
          <p className="text-xs text-ink-faint">
            Hover or tap a cell for breakdown · USD primary
          </p>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <ExecStat
          label="Market value"
          icon={<LineChart className="h-3.5 w-3.5 text-brand" />}
          content={<MarketValueBreakdown snap={snap} breakdown={breakdown} />}
        >
          {snap.total_market_value_usd ? (
            <Money
              amount={snap.total_market_value_usd}
              currency="USD"
              secondaryMode="hover"
              size="lg"
            />
          ) : (
            <div className="text-lg text-ink-faint">Update prices</div>
          )}
        </ExecStat>

        <ExecStat
          label="Unrealized"
          icon={
            (snap.unrealized_pct ?? 0) >= 0 ? (
              <TrendingUp className="h-3.5 w-3.5 text-ok" />
            ) : (
              <TrendingDown className="h-3.5 w-3.5 text-danger" />
            )
          }
          content={<UnrealizedBreakdown snap={snap} breakdown={breakdown} />}
        >
          {snap.unrealized_usd != null ? (
            <>
              <Money
                amount={snap.unrealized_usd}
                currency="USD"
                secondaryMode="hover"
                size="lg"
                signed
              />
              {snap.unrealized_pct != null && (
                <div
                  className={cn(
                    "text-xs",
                    snap.unrealized_pct >= 0 ? "text-ok" : "text-danger",
                  )}
                >
                  vs open cost {snap.unrealized_pct >= 0 ? "+" : ""}
                  {snap.unrealized_pct.toFixed(1)}%
                </div>
              )}
            </>
          ) : (
            <div className="text-lg text-ink-faint">—</div>
          )}
        </ExecStat>

        <ExecStat
          label="Realized (lifetime)"
          icon={<Wallet className="h-3.5 w-3.5 text-ink-muted" />}
          content={<RealizedBreakdown snap={snap} breakdown={breakdown} />}
        >
          <Money
            amount={snap.realized_lifetime_usd}
            currency="USD"
            secondaryMode="hover"
            size="lg"
            signed
          />
          <div className="text-[11px] text-ink-faint">
            {snap.realized_cost_basis_usd != null && d(snap.realized_cost_basis_usd) > 0 ? (
              <>
                on {formatUsd(snap.realized_cost_basis_usd)} sold
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
        </ExecStat>

        <ExecStat
          label="Open cost basis"
          icon={<Wallet className="h-3.5 w-3.5 text-ink-muted" />}
          content={<CostBasisBreakdown snap={snap} breakdown={breakdown} />}
        >
          <Money
            amount={snap.total_cost_basis_usd}
            currency="USD"
            amountCzk={snap.total_cost_basis_czk}
            secondaryMode="hover"
            size="lg"
          />
        </ExecStat>

        {snap.living_draw_12m ? (
          <ExecStat
            label="12m living draw"
            icon={<TrendingDown className="h-3.5 w-3.5 text-warn" />}
            content={<LivingDrawBreakdown draw={snap.living_draw_12m} />}
            footer={
              <Link
                to="/investments/analysis"
                className="mt-1 inline-flex items-center gap-0.5 text-[11px] font-medium text-brand hover:underline"
              >
                Full draw <ArrowRight className="h-3 w-3" />
              </Link>
            }
          >
            <Money
              amount={snap.living_draw_12m.draw_usd}
              currency="USD"
              secondaryMode="hover"
              size="lg"
              signed
            />
            <div className="text-[11px] text-ink-faint">
              Sold {formatUsd(snap.living_draw_12m.sold_usd)} · reinvested{" "}
              {formatUsd(snap.living_draw_12m.bought_usd)}
            </div>
          </ExecStat>
        ) : (
          <div className="rounded-xl border border-white/10 bg-black/20 p-3">
            <div className="label mb-1">12m living draw</div>
            <div className="text-lg text-ink-faint">—</div>
          </div>
        )}
      </div>
    </section>
  );
}
