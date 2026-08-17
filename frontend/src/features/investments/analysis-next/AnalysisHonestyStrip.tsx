import type { PortfolioSnapshot } from "../../../api/types";

/**
 * Statement-cash honesty. Optional living-vs-cashflow line only when both widgets are on screen.
 */
export function AnalysisHonestyStrip({
  snap,
  showLivingVsCashflow = false,
}: {
  snap: PortfolioSnapshot;
  showLivingVsCashflow?: boolean;
}) {
  const asOf = snap.prices_as_of ?? snap.price_status?.prices_as_of ?? null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[11px] text-ink-muted">
      {asOf ? (
        <span className="rounded-md bg-white/5 px-2 py-0.5">Marks as of {asOf}</span>
      ) : null}
      <span className="rounded-md bg-white/5 px-2 py-0.5">Cashflow from statements</span>
      <span className="rounded-md bg-white/5 px-2 py-0.5">FX = stored CNB</span>
      {showLivingVsCashflow ? (
        <span className="w-full text-ink-faint">
          Living draw uses stored value_usd only; monthly cashflow FX-fills CZK legs when
          value_usd is missing.
        </span>
      ) : null}
    </div>
  );
}
