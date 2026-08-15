import { useLocation, useNavigate } from "react-router-dom";
import { Pause, Play, Sparkles } from "lucide-react";
import { formatUsdEstimate } from "../../lib/aiCost";
import { cn } from "../../lib/cn";
import { useGrokPlus } from "./GrokPlusContext";

export function FloatingMatchChip() {
  const grok = useGrokPlus();
  const navigate = useNavigate();
  const location = useLocation();

  if (!grok.enabled || !grok.started) return null;

  const running = grok.phase === "running";
  const paused = grok.phase === "paused";
  const caught = grok.phase === "caught_up";
  const errored = grok.phase === "error";

  const statusLabel = running
    ? "Matching vendors…"
    : paused
      ? "Paused"
      : caught
        ? "Caught up"
        : errored
          ? "Stopped"
          : "Grok+";

  const proof = grok.lastMatch
    ? `${grok.lastMatch.label} → ${grok.lastMatch.categoryName}`
    : grok.message || "Waiting for the first match…";

  function goReview() {
    const onPage = location.pathname === "/new-et/categorize";
    const params = new URLSearchParams(onPage ? location.search : "");
    params.set("panel", "grokplus");
    params.delete("mode");
    navigate(`/new-et/categorize?${params.toString()}`);
  }

  return (
    <aside
      className={cn(
        "pointer-events-auto fixed z-50 w-[min(22rem,calc(100vw-1.5rem))]",
        "bottom-20 right-3 lg:bottom-6 lg:right-4",
      )}
      aria-live="polite"
    >
      <div className="rounded-2xl border border-white/10 bg-surface-raised/95 p-3 shadow-card backdrop-blur-md">
        <div className="flex items-start gap-2">
          <span
            className={cn(
              "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
              running ? "bg-brand/20 text-brand" : "bg-white/10 text-ink-muted",
            )}
            aria-hidden
          >
            <Sparkles className={cn("h-3.5 w-3.5", running && "animate-pulse")} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="truncate text-xs font-semibold text-ink">
                {running && (
                  <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-brand align-middle" />
                )}
                {statusLabel}
              </p>
              {running ? (
                <button
                  type="button"
                  className="ml-auto rounded-lg p-1 text-ink-muted hover:bg-white/5 hover:text-ink"
                  onClick={() => grok.pause()}
                  aria-label="Pause matching"
                  title="Pause"
                >
                  <Pause className="h-3.5 w-3.5" />
                </button>
              ) : (
                <button
                  type="button"
                  className="ml-auto rounded-lg p-1 text-ink-muted hover:bg-white/5 hover:text-ink"
                  onClick={() => grok.resume()}
                  aria-label="Resume matching"
                  title="Resume"
                  disabled={caught && grok.buckets.length === 0 && !errored}
                >
                  <Play className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <p className="mt-1 truncate text-[11px] text-ink-muted" title={proof}>
              {proof}
              {running && grok.lastBatchAdded > 0
                ? ` · +${grok.lastBatchAdded} this batch`
                : ""}
            </p>
            <p className="mt-1 text-[11px] text-ink-faint">
              est. {formatUsdEstimate(grok.sessionCostUsd)} this session
              {" · "}
              {formatUsdEstimate(grok.dayCostUsd)} today
              {grok.dayQuotaCap
                ? ` · ${grok.dayQuotaUsed.toLocaleString()}/${grok.dayQuotaCap.toLocaleString()} tok`
                : ""}
            </p>
          </div>
        </div>
        <button
          type="button"
          className="btn-primary mt-2.5 w-full justify-center py-1.5 text-xs"
          onClick={goReview}
        >
          Review matches{grok.buckets.length ? ` (${grok.buckets.length})` : ""}
        </button>
      </div>
    </aside>
  );
}
