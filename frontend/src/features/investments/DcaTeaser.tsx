import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { api } from "../../api/client";
import type { DcaOpportunityItem } from "../../api/types";
import { formatUsd } from "../../lib/money";
import { cn } from "../../lib/cn";

function simpleTone(item: DcaOpportunityItem): "hot" | "strong" | "warm" | "cool" {
  if (item.eligible && (item.level === "warn" || item.discount_vs_cost_pct >= 25)) {
    return "hot";
  }
  if (item.eligible) return "strong";
  if (item.signal_a || item.signal_b || item.discount_vs_cost_pct >= 5) return "warm";
  return "cool";
}

const TONE_CLS: Record<string, string> = {
  hot: "text-ok bg-ok/15",
  strong: "text-brand bg-brand/15",
  warm: "text-warn bg-warn/15",
  cool: "text-ink-muted bg-white/5",
};

/**
 * Top DCA opportunities strip for Holdings desk (links to full board).
 */
export function DcaTeaser() {
  const [items, setItems] = useState<DcaOpportunityItem[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);

  const applyBoard = (board: Awaited<ReturnType<typeof api.investmentsDcaOpportunities>>) => {
    const merged = [...(board.stocks || []), ...(board.crypto || [])]
      .sort((a, b) => b.score - a.score)
      .slice(0, 3);
    setItems(merged);
    setAsOf(board.as_of);
  };

  useEffect(() => {
    let cancelled = false;
    void api
      .investmentsDcaOpportunities()
      .then((board) => {
        if (!cancelled) applyBoard(board);
      })
      .catch(() => {
        /* optional teaser */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onPrices = () => {
      void api
        .investmentsDcaOpportunities()
        .then(applyBoard)
        .catch(() => {});
    };
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, []);

  if (items.length === 0) return null;

  return (
    <section className="card p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold tracking-wide text-brand">
            DCA opportunities
          </h2>
          <p className="text-xs text-ink-faint">
            Top ranked add-size signals{asOf ? ` · as of ${asOf}` : ""}
          </p>
        </div>
        <Link
          to="/investments/dca"
          className="inline-flex items-center gap-0.5 text-xs font-medium text-brand hover:underline"
        >
          Full board <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {items.map((o) => {
          const tone = simpleTone(o);
          return (
            <div
              key={o.ticker}
              className="rounded-xl border border-white/10 bg-black/20 p-3"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{o.ticker}</span>
                <span
                  className={cn(
                    "rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase",
                    TONE_CLS[tone],
                  )}
                >
                  {tone}
                </span>
              </div>
              <div className="mt-1 text-xs text-ink-muted">
                <span className={o.discount_vs_cost_pct >= 0 ? "text-ok" : "text-ink-faint"}>
                  {o.discount_vs_cost_pct >= 0
                    ? `−${o.discount_vs_cost_pct.toFixed(0)}% vs cost`
                    : `+${Math.abs(o.discount_vs_cost_pct).toFixed(0)}% vs cost`}
                </span>
                <span className="text-ink-faint"> · {formatUsd(o.market_value_usd)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
