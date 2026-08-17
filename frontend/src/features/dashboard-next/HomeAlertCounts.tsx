import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { cn } from "../../lib/cn";
import type { AlertBucketCounts } from "../dashboard/alertBuckets";

/** One wrapping row to /alerts — copied from classic AlertCountStrip, not imported. */
export function HomeAlertCounts({ buckets }: { buckets: AlertBucketCounts }) {
  const chips: Array<{ key: string; label: string; count: number }> = [
    { key: "spending", label: "Spending", count: buckets.spending },
    { key: "stocks", label: "Stocks", count: buckets.stocks },
    { key: "crypto", label: "Crypto", count: buckets.crypto },
  ];

  return (
    <Link
      to="/alerts"
      className="flex min-w-0 max-w-full flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-black/20 px-3 py-2.5 transition hover:border-brand/40"
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
