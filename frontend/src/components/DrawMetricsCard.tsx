import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { DrawMetrics } from "../api/types";
import { d, formatUsd } from "../lib/money";
import { cn } from "../lib/cn";
import { Spinner } from "./Spinner";

const STATUS_STYLE: Record<string, string> = {
  ok: "bg-ok/15 text-ok ring-ok/30",
  warn: "bg-warn/15 text-warn ring-warn/30",
  over: "bg-danger/15 text-danger ring-danger/30",
  "n/a": "bg-white/10 text-ink-faint ring-white/15",
};

type Props = {
  /** Compact for dashboard strip */
  compact?: boolean;
  /** Nested in a parent hero — no outer card chrome */
  embedded?: boolean;
  /** Fit a narrow column: stack metrics, wrap note. Does not hide copy. */
  narrow?: boolean;
  className?: string;
};

export function DrawMetricsCard({
  compact = false,
  embedded = false,
  narrow = false,
  className,
}: Props) {
  const [data, setData] = useState<DrawMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [softUpdating, setSoftUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasDataRef = useRef(false);
  hasDataRef.current = data != null;

  const load = useCallback(async (opts?: { soft?: boolean }) => {
    const soft = opts?.soft ?? hasDataRef.current;
    if (soft) setSoftUpdating(true);
    else setLoading(true);
    try {
      const m = await api.drawMetrics();
      setData(m);
      setError(null);
    } catch (e) {
      if (!soft) {
        setError(e instanceof Error ? e.message : "Failed");
        setData(null);
      }
      // soft failures keep last good metrics
    } finally {
      setLoading(false);
      setSoftUpdating(false);
    }
  }, []);

  useEffect(() => {
    void load({ soft: false });
  }, [load]);

  useEffect(() => {
    const onPrices = () => {
      void load({ soft: true });
    };
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, [load]);

  if (loading && !data) {
    return (
      <div
        className={cn(
          "flex items-center justify-center p-5",
          !embedded && "card",
          className,
        )}
      >
        <Spinner className="h-5 w-5" />
      </div>
    );
  }
  if ((error || !data) && !data) {
    return (
      <div
        className={cn(
          "p-4 text-sm text-ink-muted",
          !embedded && "card",
          className,
        )}
      >
        {error || "Draw metrics unavailable"}
      </div>
    );
  }
  if (!data) return null;

  const living = d(data.living_draw_12m_usd);
  const safe = d(data.safe_draw_annual_usd);
  const ratio = data.living_over_safe_ratio != null ? d(data.living_over_safe_ratio) : null;
  const maxBar = Math.max(Math.abs(living), safe, 1);
  const livingW = Math.min(100, (Math.abs(living) / maxBar) * 100);
  const safeW = Math.min(100, (safe / maxBar) * 100);
  const status = (data.status || "n/a").toLowerCase();

  return (
    <div
      className={cn(
        "min-w-0 max-w-full space-y-3",
        embedded ? "p-0" : "card p-5",
        className,
      )}
    >
      <div className="flex min-w-0 w-full items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold tracking-wide text-ok">
            Living draw vs safe draw
          </h2>
          {!compact && (
            <p className="min-w-0 max-w-full text-pretty text-xs text-ink-faint">
              Trailing 12m investment cash (sells − buys) vs capacity{" "}
              <span className="text-ink-muted">min(4% × MV, tax-free now)</span>
            </p>
          )}
          {softUpdating && (
            <p className="text-[11px] text-ink-faint">Updating marks…</p>
          )}
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ring-1",
            STATUS_STYLE[status] || STATUS_STYLE["n/a"],
          )}
        >
          {status}
        </span>
      </div>

      <div
        className={cn(
          "grid min-w-0 gap-3",
          narrow ? "grid-cols-1" : compact ? "sm:grid-cols-2" : "sm:grid-cols-3",
        )}
      >
        <Metric
          label="Living draw (12m)"
          value={formatUsd(living)}
          sub={
            living > 0
              ? "Net cash out of brokers"
              : living < 0
                ? "Net reinvested"
                : "Flat"
          }
          tone={living > safe && safe > 0 ? "danger" : living > 0 ? "warn" : "ok"}
        />
        <Metric
          label="Safe draw (annual)"
          value={formatUsd(safe)}
          sub={
            data.safe_draw_binding_constraint === "tax_free"
              ? "Bound by tax-free stock"
              : "Bound by 4% of MV"
          }
          tone="brand"
        />
        {!compact && (
          <Metric
            label="Ratio"
            value={ratio != null ? `${ratio.toFixed(2)}×` : "—"}
            sub={`MV ${formatUsd(data.portfolio_mv_usd)} · TF ${formatUsd(data.tax_free_now_usd)}`}
          />
        )}
      </div>

      <div className="space-y-2">
        <BarRow label="Living |draw|" widthPct={livingW} color="bg-warn" />
        <BarRow label="Safe capacity" widthPct={safeW} color="bg-brand" />
      </div>

      {!compact && data.note && (
        <p className="min-w-0 max-w-full text-pretty break-words text-[11px] leading-relaxed text-ink-faint">
          {data.note}
        </p>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "ok" | "warn" | "danger" | "brand";
}) {
  const toneCls =
    tone === "ok"
      ? "text-ok"
      : tone === "warn"
        ? "text-warn"
        : tone === "danger"
          ? "text-danger"
          : tone === "brand"
            ? "text-brand"
            : "text-ink";
  return (
    <div className="min-w-0 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5">
      <div className="text-[10px] font-medium uppercase tracking-wide text-ink-faint">
        {label}
      </div>
      <div className={cn("mt-0.5 break-all text-base font-semibold tabular-nums", toneCls)}>
        {value}
      </div>
      {sub && (
        <div className="mt-0.5 min-w-0 max-w-full text-pretty text-[10px] text-ink-faint">
          {sub}
        </div>
      )}
    </div>
  );
}

function BarRow({
  label,
  widthPct,
  color,
}: {
  label: string;
  widthPct: number;
  color: string;
}) {
  return (
    <div>
      <div className="mb-0.5 flex min-w-0 justify-between gap-2 text-[10px] text-ink-faint">
        <span className="min-w-0 truncate">{label}</span>
        <span className="shrink-0 tabular-nums">{widthPct.toFixed(0)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${widthPct}%` }} />
      </div>
    </div>
  );
}
