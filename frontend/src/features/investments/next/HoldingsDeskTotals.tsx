import type { TickerDigestsResponse } from "../../../api/types";
import { d, formatUsd } from "../../../lib/money";
import { cn } from "../../../lib/cn";
import { viewDeskTotals } from "./deskTotals";

function signedUsd(value: string): string {
  const n = d(value);
  const formatted = formatUsd(value);
  return n > 0 ? `+${formatted}` : formatted;
}

function signedPct(pct: number): string {
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

/**
 * Sticky full-book totals from digest.portfolio. Never substitutes cost as MV.
 */
export function HoldingsDeskTotals({
  portfolio,
}: {
  portfolio: TickerDigestsResponse["portfolio"];
}) {
  const view = viewDeskTotals(portfolio);
  const unrealizedTone =
    view.unrealizedUsd == null
      ? "text-ink-faint"
      : d(view.unrealizedUsd) >= 0
        ? "text-ok"
        : "text-danger";

  return (
    <div className="sticky top-[3.25rem] z-20 bg-surface/90 py-2 backdrop-blur lg:top-0">
      <p className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-sm tabular-nums">
        <span className="text-ink-faint">Market</span>
        {view.mvMissing ? (
          <span className="text-ink-faint">
            — <span className="text-[11px] font-medium uppercase tracking-wide">Needs quote</span>
          </span>
        ) : (
          <span className="font-semibold text-ink">{formatUsd(view.mvUsd)}</span>
        )}
        <span className="text-ink-faint">·</span>
        <span className="text-ink-faint">FIFO cost</span>
        <span className="text-ink-muted">{formatUsd(view.costUsd)}</span>
        <span className="text-ink-faint">·</span>
        <span className="text-ink-faint">Unrealized</span>
        {view.unrealizedUsd == null ? (
          <span className="text-ink-faint">—</span>
        ) : (
          <span className={cn("font-medium", unrealizedTone)}>
            {signedUsd(view.unrealizedUsd)}
            {view.unrealizedPct != null ? (
              <span className="ml-1 font-normal">({signedPct(view.unrealizedPct)})</span>
            ) : null}
          </span>
        )}
      </p>
    </div>
  );
}
