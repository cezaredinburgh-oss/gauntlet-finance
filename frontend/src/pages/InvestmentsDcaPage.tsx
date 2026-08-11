import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { DcaBoardResponse, DcaOpportunityItem } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import { formatUsd } from "../lib/money";
import { cn } from "../lib/cn";
import { InvestmentsPageShell } from "../features/investments";

/** Opportunity visual tier — green/hot = stronger add signal. */
type OppTone = "hot" | "strong" | "warm" | "cool";

/**
 * Color from absolute signals first (eligible / deep discount), then list rank
 * so a lone strong name still reads green and weaker names stay muted.
 */
function opportunityTone(
  item: DcaOpportunityItem,
  rankIndex: number,
  listLength: number,
): OppTone {
  const rankFrac = listLength <= 1 ? 0 : rankIndex / (listLength - 1); // 0 = best
  const deep =
    item.level === "warn" ||
    item.discount_vs_cost_pct >= 25 ||
    (item.eligible && rankFrac <= 0.2);

  if (item.eligible && deep) return "hot";
  if (item.eligible) return "strong";

  const solidSignal =
    item.signal_a ||
    item.signal_b ||
    item.discount_vs_cost_pct >= 5 ||
    (item.pullback_pct != null && item.pullback_pct >= 10) ||
    (item.below_52w_avg_pct != null && item.below_52w_avg_pct >= 5);

  if (solidSignal || rankFrac <= 0.5) return "warm";
  return "cool";
}

const TICKER_TONE: Record<OppTone, string> = {
  hot: "bg-ok/20 text-ok ring-1 ring-ok/45",
  strong: "bg-brand/20 text-brand ring-1 ring-brand/40",
  warm: "bg-warn/15 text-warn ring-1 ring-warn/35",
  cool: "bg-white/8 text-ink-muted ring-1 ring-white/15",
};

const BAR_TONE: Record<OppTone, string> = {
  hot: "bg-ok",
  strong: "bg-brand",
  warm: "bg-warn/80",
  cool: "bg-white/25",
};

function scoreBarWidth(rankIndex: number, listLength: number): string {
  if (listLength <= 1) return "100%";
  const strength = 1 - rankIndex / (listLength - 1);
  return `${Math.round(18 + strength * 82)}%`;
}

function discountLabel(v: number): string {
  // positive = mark below avg cost
  if (v >= 0) return `−${v.toFixed(0)}% vs cost`;
  return `+${Math.abs(v).toFixed(0)}% vs cost`;
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
          {items.map((item, i) => {
            const tone = opportunityTone(item, i, items.length);
            return (
            <li key={item.ticker} className="px-4 py-3 hover:bg-white/[0.02]">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        "inline-flex rounded-md px-2 py-0.5 font-mono text-xs font-bold tracking-wide",
                        TICKER_TONE[tone],
                      )}
                      title={`Rank #${i + 1} · score ${item.score.toFixed(1)} · ${tone}`}
                    >
                      {item.ticker}
                    </span>
                    <span className="text-[11px] tabular-nums text-ink-faint">
                      score {item.score.toFixed(1)}
                    </span>
                  </div>

                  <div className="mt-1.5 h-1 w-full max-w-[12rem] overflow-hidden rounded-full bg-white/5">
                    <div
                      className={cn("h-full rounded-full", BAR_TONE[tone])}
                      style={{ width: scoreBarWidth(i, items.length) }}
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
                </div>
              </div>
            </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function ToneLegend() {
  const items: Array<{ tone: OppTone; label: string }> = [
    { tone: "hot", label: "Hot" },
    { tone: "strong", label: "Strong" },
    { tone: "warm", label: "Warm" },
    { tone: "cool", label: "Low" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-faint">
      <span className="text-ink-muted">Color</span>
      {items.map(({ tone, label }) => (
        <span key={tone} className="inline-flex items-center gap-1.5">
          <span
            className={cn(
              "inline-block h-2.5 w-2.5 rounded-sm ring-1 ring-inset",
              tone === "hot" && "bg-ok ring-ok/50",
              tone === "strong" && "bg-brand ring-brand/50",
              tone === "warm" && "bg-warn ring-warn/50",
              tone === "cool" && "bg-white/25 ring-white/20",
            )}
          />
          {label}
        </span>
      ))}
    </div>
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

  const stocks = board?.stocks ?? [];
  const crypto = board?.crypto ?? [];

  return (
    <InvestmentsPageShell
      active="dca"
      title="DCA opportunities"
      subtitle="Rank holdings by add-size signal — below cost, 3M pullback, under 52-week average"
    >
      {loading && !board && <PageLoader label="Loading DCA board…" />}

      {error && !board && (
        <EmptyState
          title="Couldn’t load DCA board"
          description={error}
          action={
            <button type="button" className="btn-primary" onClick={() => void load()}>
              Retry
            </button>
          }
        />
      )}

      {board && (
        <>
          <div className="card flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 text-xs text-ink-faint">
            <span className="font-medium text-ink-muted">As of {board.as_of ?? "—"}</span>
            <ToneLegend />
            {board.meta?.history_available === false && (
              <span className="rounded-lg bg-warn/10 px-2 py-0.5 text-warn">
                History offline — ranking from cost discount only
              </span>
            )}
            <Link
              to="/expenses/alerts"
              className="ml-auto font-medium text-brand hover:underline"
            >
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
            Ranked by continuous score (cost discount, pullback, 52-week average, days
            since last buy, size). Color tracks opportunity strength only — alert
            eligibility lives on the Alerts page. Not investment advice — statement lots +
            live marks only.
          </p>
        </>
      )}
    </InvestmentsPageShell>
  );
}
