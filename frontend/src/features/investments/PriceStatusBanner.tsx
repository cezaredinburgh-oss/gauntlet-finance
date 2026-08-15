import { useEffect, useState } from "react";
import type { PortfolioSnapshot } from "../../api/types";
import { cn } from "../../lib/cn";

/**
 * Price quality + in-flight fetch notice for Holdings / wealth views.
 * Listens for prices-refresh-start|end from Layout soft tick and post-upload.
 */
export function PriceStatusBanner({ snap }: { snap: PortfolioSnapshot }) {
  const ps = snap.price_status;
  const mode =
    ps?.mode ||
    (snap.missing_quotes.length
      ? "partial"
      : snap.prices_as_of
        ? "live_ok"
        : "empty");
  const note =
    ps?.note ||
    (snap.prices_as_of
      ? `Price data · ${snap.quote_count} quotes · as of ${snap.prices_as_of}`
      : "No prices loaded");

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

  const needsQuotes = snap.missing_quotes.length > 0 || mode === "empty";

  return (
    <div
      className={cn(
        "rounded-xl border px-4 py-3 text-sm",
        mode === "empty" || mode === "stale" || fetching
          ? "border-warn/30 bg-warn/10 text-warn"
          : mode === "partial"
            ? "border-warn/30 bg-warn/10 text-warn"
            : "border-brand/30 bg-brand/10 text-brand",
      )}
    >
      {fetching ? (
        <div>
          <div className="flex items-center gap-2 font-medium">
            <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current/30 border-t-current" />
            Working — fetching market quotes
          </div>
          <p className="mt-1 text-[11px] font-normal opacity-90">
            {etaLeft > 0
              ? `Typically ~${etaLeft}s remaining (estimate). Marks update when this finishes.`
              : "Still working — the request is in flight."}
          </p>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
            <div className="bar-indet h-full w-1/3 rounded-full bg-current" />
          </div>
        </div>
      ) : (
        <div>{note}</div>
      )}
      {ps?.mode_note && !fetching && (
        <div className="mt-1 text-[11px] opacity-80">{ps.mode_note}</div>
      )}
      {needsQuotes && !fetching && (
        <div className="mt-1 text-[11px] opacity-90">
          Live marks refresh automatically on Home / Investments (~90s cadence, and
          immediately when you open those pages). After a new investment import, quotes
          are requested right away.
        </div>
      )}
    </div>
  );
}
