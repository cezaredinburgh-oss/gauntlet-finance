import type { DcaOpportunityItem } from "../../../api/types";
import { formatUsd } from "../../../lib/money";
import { cn } from "../../../lib/cn";
import { opportunityTone, type OppTone } from "./opportunityTone";

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
  if (v >= 0) return `−${v.toFixed(0)}% vs cost`;
  return `+${Math.abs(v).toFixed(0)}% vs cost`;
}

export function DcaCardNext({
  item,
  rankIndex,
  listLength,
  historyAvailable,
}: {
  item: DcaOpportunityItem;
  rankIndex: number;
  listLength: number;
  historyAvailable: boolean;
}) {
  const tone = opportunityTone(item, rankIndex, listLength, historyAvailable);
  const threeMTitle = item.high_3m ? `3M high ${formatUsd(item.high_3m)}` : undefined;
  const avg52Title = item.avg_52w ? `52w avg ${formatUsd(item.avg_52w)}` : undefined;

  return (
    <li className="px-4 py-3 hover:bg-white/[0.02]">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex rounded-md px-2 py-0.5 font-mono text-xs font-bold tracking-wide",
                TICKER_TONE[tone],
              )}
              title={`Rank #${rankIndex + 1} · score ${item.score.toFixed(1)}`}
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
              style={{ width: scoreBarWidth(rankIndex, listLength) }}
            />
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="rounded-md bg-white/5 px-1.5 py-0.5 tabular-nums text-ink">
              {discountLabel(item.discount_vs_cost_pct)}
            </span>
            <span
              className="rounded-md bg-white/5 px-1.5 py-0.5 tabular-nums text-ink-muted"
              title={threeMTitle}
            >
              3M {item.pullback_pct != null ? `−${item.pullback_pct.toFixed(0)}%` : "—"}
            </span>
            <span
              className="rounded-md bg-white/5 px-1.5 py-0.5 tabular-nums text-ink-muted"
              title={avg52Title}
            >
              52w{" "}
              {item.below_52w_avg_pct != null
                ? item.below_52w_avg_pct >= 0
                  ? `−${item.below_52w_avg_pct.toFixed(0)}%`
                  : `+${Math.abs(item.below_52w_avg_pct).toFixed(0)}%`
                : "—"}
            </span>
            <span
              className="rounded-md bg-white/5 px-1.5 py-0.5 tabular-nums text-ink-muted"
              title="size term = log10(MV+1)"
            >
              MV {formatUsd(item.market_value_usd)}
            </span>
            <span className="text-[10px] text-ink-faint">size term = log10(MV+1)</span>
          </div>

          <div className="mt-1 text-[11px] text-ink-faint">
            last buy {item.last_buy || "—"} · {item.days_since_buy}d since buy
          </div>

          <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-ink-faint">
            <span className="tabular-nums">
              {formatUsd(item.mark)} / avg {formatUsd(item.avg_cost_usd)}
            </span>
            <span className="tabular-nums">{item.weight_pct.toFixed(1)}% book</span>
          </div>
        </div>
      </div>
    </li>
  );
}
