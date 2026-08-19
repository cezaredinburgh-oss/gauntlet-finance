import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Minus, Pause, Play, Sparkles, X } from "lucide-react";
import { formatUsdEstimate } from "../../lib/aiCost";
import { cn } from "../../lib/cn";
import {
  grokPlusMinimizedLabel,
  grokPlusStatusLabel,
} from "../../lib/grokPlus";
import { Spinner } from "../../components/Spinner";
import { useGrokPlus } from "./GrokPlusContext";

export { grokPlusMinimizedLabel, grokPlusStatusLabel };

export function GrokPlusStatus({
  variant,
}: {
  variant: "embedded" | "float";
}) {
  const grok = useGrokPlus();
  const navigate = useNavigate();
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (grok.phase !== "running") {
      setElapsed(0);
      return;
    }
    const t0 = Date.now();
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 500);
    return () => window.clearInterval(id);
  }, [grok.phase]);

  if (!grok.enabled || !grok.started) return null;
  if (grok.dismissed && variant === "float") return null;

  const running = grok.phase === "running";
  const label = grokPlusStatusLabel(grok.phase, grok.buckets.length);
  const miniLabel = grokPlusMinimizedLabel(grok.phase, grok.buckets.length);
  const proof = grok.lastMatch
    ? `${grok.lastMatch.label} → ${grok.lastMatch.categoryName}`
    : grok.message || "Starting leftover matching…";

  if (grok.minimized) {
    return (
      <div
        className={cn(
          "flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2",
          variant === "float" && "shadow-card backdrop-blur-md",
        )}
      >
        {running ? (
          <Spinner className="h-3.5 w-3.5 border-t-brand" />
        ) : (
          <span
            className={cn(
              "h-2 w-2 shrink-0 rounded-full",
              grok.phase === "caught_up" ? "bg-ok" : "bg-ink-faint",
            )}
          />
        )}
        <p className="min-w-0 flex-1 truncate text-xs font-medium text-ink">{miniLabel}</p>
        <button
          type="button"
          className="btn-ghost px-1.5 py-0.5 text-[11px]"
          onClick={() => grok.setMinimized(false)}
        >
          Expand
        </button>
        {variant === "float" ? (
          <button type="button" className="btn-ghost p-1" aria-label="Close" onClick={() => grok.dismiss()}>
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "rounded-xl border px-3 py-2.5",
        running ? "border-brand/40 bg-brand/10" : "border-white/10 bg-white/[0.03]",
        variant === "float" && "bg-surface-raised/95 shadow-card backdrop-blur-md",
      )}
      aria-live="polite"
      aria-busy={running}
    >
      <div className="flex items-start gap-2">
        <span
          className={cn(
            "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
            running ? "bg-brand/25 text-brand" : "bg-white/10 text-ink-muted",
          )}
        >
          {running ? (
            <Spinner className="h-3.5 w-3.5 border-t-brand" />
          ) : (
            <Sparkles className="h-3.5 w-3.5" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <p className="min-w-0 flex-1 truncate text-xs font-semibold text-ink">{label}</p>
            <button
              type="button"
              className="rounded-lg p-1 text-ink-muted hover:bg-white/5"
              aria-label="Minimize"
              onClick={() => grok.setMinimized(true)}
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            {running ? (
              <button
                type="button"
                className="rounded-lg p-1 text-ink-muted hover:bg-white/5"
                aria-label="Pause"
                onClick={() => grok.pause()}
              >
                <Pause className="h-3.5 w-3.5" />
              </button>
            ) : (
              <button
                type="button"
                className="rounded-lg p-1 text-ink-muted hover:bg-white/5"
                aria-label="Resume"
                onClick={() => grok.resume()}
              >
                <Play className="h-3.5 w-3.5" />
              </button>
            )}
            {variant === "float" ? (
              <button
                type="button"
                className="rounded-lg p-1 text-ink-muted hover:bg-white/5"
                aria-label="Close"
                onClick={() => grok.dismiss()}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
          <p className="mt-1 truncate text-[11px] text-ink-muted" title={proof}>
            {running ? `Still working${elapsed ? ` · ${elapsed}s` : ""} · ` : ""}
            {proof}
            {running && grok.lastBatchAdded > 0 ? ` · +${grok.lastBatchAdded} this batch` : ""}
          </p>
          {running ? (
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
              <div className="bar-indet h-full w-1/3 rounded-full bg-brand" />
            </div>
          ) : null}
          <p className="mt-1 text-[11px] text-ink-faint">
            est. {formatUsdEstimate(grok.sessionCostUsd)} this session
            {grok.dayQuotaCap
              ? ` · ${grok.dayQuotaUsed.toLocaleString()}/${grok.dayQuotaCap.toLocaleString()} tok`
              : ""}
          </p>
        </div>
      </div>
      {variant === "float" ? (
        <button
          type="button"
          className="btn-primary mt-2.5 w-full justify-center py-1.5 text-xs"
          onClick={() => {
            grok.setMinimized(false);
            navigate("/expenses/categorize?panel=grokplus");
          }}
        >
          Review matches{grok.buckets.length ? ` (${grok.buckets.length})` : ""}
        </button>
      ) : null}
    </div>
  );
}
