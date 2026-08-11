import type { PortfolioSnapshot } from "../../api/types";
import { cn } from "../../lib/cn";

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
  return (
    <div
      className={cn(
        "rounded-xl border px-4 py-3 text-sm",
        mode === "empty" || mode === "stale"
          ? "border-warn/30 bg-warn/10 text-warn"
          : mode === "partial"
            ? "border-warn/30 bg-warn/10 text-warn"
            : "border-brand/30 bg-brand/10 text-brand",
      )}
    >
      <div>{note}</div>
      {ps?.mode_note && (
        <div className="mt-1 text-[11px] opacity-80">{ps.mode_note}</div>
      )}
      {(snap.missing_quotes.length > 0 || mode === "empty") && (
        <div className="mt-1 text-[11px] opacity-90">
          Use <strong>Update prices</strong> in the header for live marks.
        </div>
      )}
    </div>
  );
}
