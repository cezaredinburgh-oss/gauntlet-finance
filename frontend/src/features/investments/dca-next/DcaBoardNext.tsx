import type { DcaOpportunityItem } from "../../../api/types";
import { DcaCardNext } from "./DcaCardNext";

function DcaColumn({
  title,
  items,
  emptyHint,
  historyAvailable,
}: {
  title: string;
  items: DcaOpportunityItem[];
  emptyHint: string;
  historyAvailable: boolean;
}) {
  return (
    <section className="card flex min-h-[12rem] flex-col overflow-hidden">
      <div className="border-b border-white/5 px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
          <span className="text-[11px] text-ink-faint">
            {items.length} name{items.length === 1 ? "" : "s"} · best first
          </span>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-ink-faint">
          {emptyHint}
        </div>
      ) : (
        <ul className="divide-y divide-white/5">
          {items.map((item, i) => (
            <DcaCardNext
              key={item.ticker}
              item={item}
              rankIndex={i}
              listLength={items.length}
              historyAvailable={historyAvailable}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

export function DcaBoardNext({
  stocks,
  crypto,
  historyAvailable,
}: {
  stocks: DcaOpportunityItem[];
  crypto: DcaOpportunityItem[];
  historyAvailable: boolean;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <DcaColumn
        title="Stocks"
        items={stocks}
        historyAvailable={historyAvailable}
        emptyHint="No priced stock/ETF positions on the board yet."
      />
      <DcaColumn
        title="Crypto"
        items={crypto}
        historyAvailable={historyAvailable}
        emptyHint="No priced crypto positions on the board yet."
      />
    </div>
  );
}
