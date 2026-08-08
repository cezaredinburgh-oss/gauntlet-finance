import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { format } from "date-fns";
import type { PeriodKey } from "../api/types";
import { cn } from "../lib/cn";
import {
  resolveTimeframe,
  resolveCalendarMonth,
  shiftCalendarMonth,
  monthAnchorFromValue,
  canGoNextMonth,
  isMonthStyleKey,
  type TimeframeValue,
} from "../lib/timeframe";

export type { TimeframeValue };
export { defaultTimeframe } from "../lib/timeframe";

const PRESETS: { key: PeriodKey; label: string }[] = [
  { key: "this_month", label: "This month" },
  { key: "last_month", label: "Last month" },
  { key: "last_30d", label: "Last 30d" },
  { key: "last_6m", label: "Last 6m" },
  { key: "this_year", label: "This year" },
  { key: "last_year", label: "Last year" },
  { key: "all_time", label: "All time" },
  { key: "custom", label: "Custom" },
];

type Props = {
  value: TimeframeValue;
  onChange: (v: TimeframeValue) => void;
};

export function TimeframePicker({ value, onChange }: Props) {
  const [customFrom, setCustomFrom] = useState(value.from || "");
  const [customTo, setCustomTo] = useState(value.to);
  const showCustom = value.key === "custom";

  const monthAnchor = monthAnchorFromValue(value);
  const monthLabel = format(monthAnchor, "MMMM yyyy");
  const nextEnabled = canGoNextMonth(value);
  const monthActive = isMonthStyleKey(value.key);

  return (
    <div className="space-y-3">
      {/* Calendar month stepper */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 rounded-xl border border-white/10 bg-white/[0.03] p-1">
          <button
            type="button"
            aria-label="Previous month"
            className="rounded-lg p-1.5 text-ink-muted transition hover:bg-white/10 hover:text-ink"
            onClick={() => onChange(shiftCalendarMonth(value, -1))}
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            className={cn(
              "min-w-[9.5rem] px-2 py-1 text-center text-sm font-semibold tabular-nums transition",
              monthActive ? "text-brand" : "text-ink",
            )}
            title="Select this calendar month"
            onClick={() =>
              onChange(
                resolveCalendarMonth(monthAnchor.getFullYear(), monthAnchor.getMonth()),
              )
            }
          >
            {monthLabel}
          </button>
          <button
            type="button"
            aria-label="Next month"
            disabled={!nextEnabled}
            className={cn(
              "rounded-lg p-1.5 transition",
              nextEnabled
                ? "text-ink-muted hover:bg-white/10 hover:text-ink"
                : "cursor-not-allowed text-ink-faint opacity-40",
            )}
            onClick={() => {
              if (nextEnabled) onChange(shiftCalendarMonth(value, 1));
            }}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
        <button
          type="button"
          className={cn(
            "rounded-lg px-2.5 py-1.5 text-xs font-medium transition",
            value.key === "this_month"
              ? "bg-brand/20 text-brand ring-1 ring-brand/40"
              : "bg-white/5 text-ink-muted hover:bg-white/10 hover:text-ink",
          )}
          onClick={() => onChange(resolveTimeframe("this_month"))}
        >
          Jump to this month
        </button>
      </div>

      {/* Preset chips */}
      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => {
              if (p.key === "custom") {
                const v = resolveTimeframe(
                  "custom",
                  customFrom || value.from || undefined,
                  customTo || value.to,
                );
                setCustomFrom(v.from || "");
                setCustomTo(v.to);
                onChange(v);
              } else {
                onChange(resolveTimeframe(p.key));
              }
            }}
            className={cn(
              "rounded-lg px-2.5 py-1.5 text-xs font-medium transition",
              value.key === p.key
                ? "bg-brand/20 text-brand ring-1 ring-brand/40"
                : "bg-white/5 text-ink-muted hover:bg-white/10 hover:text-ink",
            )}
          >
            {p.label}
          </button>
        ))}
      </div>
      {showCustom && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-ink-faint">
            From
            <input
              type="date"
              className="input mt-1 max-w-[11rem]"
              value={customFrom}
              onChange={(e) => setCustomFrom(e.target.value)}
            />
          </label>
          <label className="text-xs text-ink-faint">
            To
            <input
              type="date"
              className="input mt-1 max-w-[11rem]"
              value={customTo}
              onChange={(e) => setCustomTo(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn-secondary text-xs"
            onClick={() => onChange(resolveTimeframe("custom", customFrom, customTo))}
          >
            Apply
          </button>
        </div>
      )}
    </div>
  );
}
