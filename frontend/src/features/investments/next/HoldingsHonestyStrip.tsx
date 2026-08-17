import { useEffect, useState } from "react";
import type { TickerDigestsResponse } from "../../../api/types";
import { cn } from "../../../lib/cn";

/**
 * Digest-only price honesty. Replaces PriceStatusBanner on the next desk.
 */
export function HoldingsHonestyStrip({
  response,
}: {
  response: TickerDigestsResponse;
}) {
  const missing = response.tickers.filter((t) => t.missing_price).length;
  const asOf = response.prices_as_of;

  const [fetching, setFetching] = useState(false);
  const [etaLeft, setEtaLeft] = useState(0);

  useEffect(() => {
    let etaTimer: number | null = null;
    const onStart = (ev: Event) => {
      const detail = (ev as CustomEvent<{ etaSeconds?: number }>).detail;
      const eta = Math.max(5, Math.min(60, detail?.etaSeconds ?? 12));
      setFetching(true);
      setEtaLeft(eta);
      if (etaTimer != null) window.clearInterval(etaTimer);
      etaTimer = window.setInterval(() => {
        setEtaLeft((n) => Math.max(0, n - 1));
      }, 1000);
    };
    const onEnd = () => {
      setFetching(false);
      setEtaLeft(0);
      if (etaTimer != null) {
        window.clearInterval(etaTimer);
        etaTimer = null;
      }
    };
    window.addEventListener("prices-refresh-start", onStart);
    window.addEventListener("prices-refresh-end", onEnd);
    window.addEventListener("prices-updated", onEnd);
    return () => {
      window.removeEventListener("prices-refresh-start", onStart);
      window.removeEventListener("prices-refresh-end", onEnd);
      window.removeEventListener("prices-updated", onEnd);
      if (etaTimer != null) window.clearInterval(etaTimer);
    };
  }, []);

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[11px]",
        fetching
          ? "border-warn/30 bg-warn/10 text-warn"
          : "border-white/10 bg-white/[0.03] text-ink-muted",
      )}
      aria-live="polite"
    >
      {fetching ? (
        <>
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current/30 border-t-current" />
          <span className="font-medium">Fetching marks…</span>
          <span className="opacity-80">
            {etaLeft > 0 ? `~${etaLeft}s` : "in flight"}
          </span>
        </>
      ) : (
        <>
          <span className="rounded-md bg-white/5 px-2 py-0.5">
            {asOf ? `Marks as of ${asOf}` : "No marks yet"}
          </span>
          <span
            className={cn(
              "rounded-md px-2 py-0.5",
              missing > 0 ? "bg-warn/15 text-warn" : "bg-ok/15 text-ok",
            )}
          >
            {missing > 0 ? `${missing} unpriced` : "All priced"}
          </span>
          <span className="rounded-md bg-white/5 px-2 py-0.5">Soft refresh ~90s</span>
        </>
      )}
    </div>
  );
}
