import type { PortfolioSnapshot } from "../../api/types";
import { Money } from "../../components/Money";
import { HoverPanel } from "../../components/HoverPanel";
import { formatQty, formatUsd } from "../../lib/money";
import { cn } from "../../lib/cn";

export function TaxRunwayCard({
  snap,
  focus,
  runwayRef,
  embedded = false,
}: {
  snap: PortfolioSnapshot;
  focus?: string;
  runwayRef?: React.Ref<HTMLDivElement>;
  /** When true, no outer card chrome — sits inside HoldingsHero */
  embedded?: boolean;
}) {
  return (
    <div
      ref={runwayRef}
      className={cn(
        "scroll-mt-24",
        embedded ? "pt-1" : "card p-5",
        focus === "tax_runway" && "ring-2 ring-brand/50 rounded-xl",
      )}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">Tax-free runway</h2>
        <span className="pill-good">
          Available {formatUsd(snap.tax_runway.available_usd)}
        </span>
        <span className="pill-warn">
          Still locked {formatUsd(snap.tax_runway.locked_usd)}
        </span>
      </div>
      <p className="mb-4 text-xs text-ink-faint">
        Czech 3-year planning buckets · hover for ticker split (MV when priced, else cost).
        Filing detail lives under Tax.
      </p>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {snap.tax_runway.buckets.map((b, i) => (
          <HoverPanel
            key={b.key}
            content={
              b.tickers.length === 0 ? (
                <div className="text-xs text-ink-faint">No lots in this bucket</div>
              ) : (
                <ul className="space-y-1">
                  {b.tickers.map((t) => (
                    <li key={t.ticker} className="flex justify-between gap-3 text-xs">
                      <span>
                        {t.ticker}{" "}
                        <span className="text-ink-faint">({formatQty(t.quantity)})</span>
                      </span>
                      <span className="font-medium">{formatUsd(t.amount_usd)}</span>
                    </li>
                  ))}
                </ul>
              )
            }
          >
            <div
              className={cn(
                "rounded-xl border p-3 transition hover:border-brand/40",
                i === 0 ? "border-ok/30 bg-ok/5" : "border-white/5 bg-white/[0.02]",
              )}
            >
              <div className="label mb-1">{b.label}</div>
              <Money
                amount={b.amount_usd}
                currency="USD"
                secondaryMode="hover"
                size="lg"
              />
            </div>
          </HoverPanel>
        ))}
      </div>
    </div>
  );
}
