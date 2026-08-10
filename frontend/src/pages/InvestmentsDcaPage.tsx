import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { DcaBoardResponse, DcaOpportunityItem } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import { formatUsd } from "../lib/money";
import { cn } from "../lib/cn";
import { InvestmentsSubNav } from "../features/investments";

/**
 * Monochrome ticker intensity: brighter = larger opportunity within the list.
 * rankIndex 0 = strongest.
 */
function monoTickerClass(rankIndex: number, listLength: number): string {
  if (listLength <= 1) {
    return "bg-white/20 text-white ring-1 ring-white/40";
  }
  const t = rankIndex / (listLength - 1); // 0 strong → 1 weak
  if (t <= 0.2) return "bg-white/22 text-white ring-1 ring-white/45";
  if (t <= 0.4) return "bg-white/16 text-white/90 ring-1 ring-white/30";
  if (t <= 0.6) return "bg-white/12 text-white/70 ring-1 ring-white/20";
  if (t <= 0.8) return "bg-white/8 text-white/50 ring-1 ring-white/12";
  return "bg-white/5 text-white/35 ring-1 ring-white/8";
}

function monoBarWidth(rankIndex: number, listLength: number): string {
  if (listLength <= 1) return "100%";
  const strength = 1 - rankIndex / (listLength - 1);
  return `${Math.round(18 + strength * 82)}%`;
}

function discountLabel(v: number): string {
  // positive = mark below avg cost
  if (v >= 0) return `−${v.toFixed(0)}% vs cost`;
  return `+${Math.abs(v).toFixed(0)}% vs cost`;
}

function gateLabel(blockers: string[]): string {
  if (!blockers.length) return "";
  const map: Record<string, string> = {
    cooldown: "recent buy",
    concentration: "concentrated",
    materiality: "small size",
    stale_price: "stale price",
    unpriced: "unpriced",
  };
  return blockers.map((b) => map[b] || b).join(" · ");
}

function DcaColumn({
  title,
  items,
  emptyHint,
}: {
  title: string;
  items: DcaOpportunityItem[];
  emptyHint: string;
}) {
  return (
    <section className="card flex min-h-[12rem] flex-col overflow-hidden">
      <div className="border-b border-white/5 px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
          <span className="text-[11px] text-ink-faint">
            {items.length} name{items.length === 1 ? "" : "s"} · best first
          </span>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-ink-faint">
          {emptyHint}
        </div>
      ) : (
        <ul className="divide-y divide-white/5">
          {items.map((item, i) => (
            <li key={item.ticker} className="px-4 py-3 hover:bg-white/[0.02]">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        "inline-flex rounded-md px-2 py-0.5 font-mono text-xs font-bold tracking-wide",
                        monoTickerClass(i, items.length),
                      )}
                      title={`Rank #${i + 1} · score ${item.score.toFixed(1)}`}
                    >
                      {item.ticker}
                    </span>
                    {item.eligible ? (
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                          item.level === "warn"
                            ? "bg-white/15 text-white"
                            : "bg-white/10 text-white/80",
                        )}
                      >
                        Active
                      </span>
                    ) : (
                      <span
                        className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase text-ink-faint"
                        title={gateLabel(item.gate_blockers) || "Below alert thresholds"}
                      >
                        Watch
                      </span>
                    )}
                    <span className="text-[11px] tabular-nums text-ink-faint">
                      score {item.score.toFixed(1)}
                    </span>
                  </div>

                  <div className="mt-1.5 h-1 w-full max-w-[12rem] overflow-hidden rounded-full bg-white/5">
                    <div
                      className="h-full rounded-full bg-white/40"
                      style={{ width: monoBarWidth(i, items.length) }}
                    />
                  </div>

                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-muted">
                    <span className="tabular-nums text-ink">{discountLabel(item.discount_vs_cost_pct)}</span>
                    <span className="tabular-nums">
                      3M {item.pullback_pct != null ? `−${item.pullback_pct.toFixed(0)}%` : "—"}
                    </span>
                    <span className="tabular-nums">
                      52w avg{" "}
                      {item.below_52w_avg_pct != null
                        ? item.below_52w_avg_pct >= 0
                          ? `−${item.below_52w_avg_pct.toFixed(0)}%`
                          : `+${Math.abs(item.below_52w_avg_pct).toFixed(0)}%`
                        : "—"}
                    </span>
                    <span>{item.days_since_buy}d since buy</span>
                  </div>

                  <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-ink-faint">
                    <span className="tabular-nums">
                      {formatUsd(item.mark)} / avg {formatUsd(item.avg_cost_usd)}
                    </span>
                    <span className="tabular-nums">MV {formatUsd(item.market_value_usd)}</span>
                    <span className="tabular-nums">{item.weight_pct.toFixed(1)}% book</span>
                  </div>

                  {!item.eligible && item.gate_blockers.length > 0 && (
                    <div className="mt-1 text-[10px] text-ink-faint">
                      Gated: {gateLabel(item.gate_blockers)}
                    </div>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function InvestmentsDcaPage() {
  const [board, setBoard] = useState<DcaBoardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (opts?: { quiet?: boolean }) => {
    const quiet = opts?.quiet ?? false;
    if (!quiet) setLoading(true);
    try {
      const r = await api.investmentsDcaOpportunities();
      setBoard(r);
      setError(null);
    } catch (e) {
      if (!quiet) setError(e instanceof Error ? e.message : "Failed");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onPrices = () => {
      void load({ quiet: true });
    };
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, [load]);

  if (loading && !board) return <PageLoader label="Loading DCA board…" />;
  if (error && !board) {
    return <EmptyState title="Couldn’t load DCA board" description={error} />;
  }

  const stocks = board?.stocks ?? [];
  const crypto = board?.crypto ?? [];
  const activeCount =
    stocks.filter((x) => x.eligible).length + crypto.filter((x) => x.eligible).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">DCA opportunities</h1>
        <p className="text-sm text-ink-muted">
          Rank existing holdings by add-size signal — below your cost, 3M pullback, and
          under 52-week average. Brighter tickers = larger opportunity in that list.
        </p>
        <InvestmentsSubNav active="dca" />
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-ink-faint">
        <span>
          As of {board?.as_of ?? "—"}
          {activeCount > 0 ? ` · ${activeCount} active` : " · no active alerts right now"}
        </span>
        {board?.meta?.history_available === false && (
          <span className="rounded bg-white/5 px-2 py-0.5">
            History offline — ranking from cost discount only
          </span>
        )}
        <Link to="/expenses/alerts" className="text-brand hover:underline">
          Alerts →
        </Link>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <DcaColumn
          title="Stocks"
          items={stocks}
          emptyHint="No priced stock/ETF positions on the board yet."
        />
        <DcaColumn
          title="Crypto"
          items={crypto}
          emptyHint="No priced crypto positions on the board yet."
        />
      </div>

      <p className="text-[11px] leading-relaxed text-ink-faint">
        Active = clears alert gates (material size, {board?.meta?.cooldown_days ?? 21}d since
        last buy, weight ≤{board?.meta?.max_weight_pct ?? 35}%, fresh mark) and hits Signal A
        or B. Watch = still ranked by continuous score but gated or below thresholds. Not
        investment advice — statement lots + live marks only.
      </p>
    </div>
  );
}
