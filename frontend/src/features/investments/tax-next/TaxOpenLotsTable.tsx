import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { TaxOpenLot, TaxOpenPosition } from "../../../api/types";
import { EmptyState } from "../../../components/Spinner";
import { formatCzk, formatQty, formatUsd } from "../../../lib/money";

function lotsFor(position: TaxOpenPosition): TaxOpenLot[] {
  return [...(position.lots ?? [])].sort((a, b) => {
    const byDate = a.acquisition_date.localeCompare(b.acquisition_date);
    if (byDate !== 0) return byDate;
    return a.lot_id.localeCompare(b.lot_id);
  });
}

function LotSubtable({ lots }: { lots: TaxOpenLot[] }) {
  if (lots.length === 0) {
    return <p className="px-3 py-2 text-xs text-ink-faint">No lot rows on this ticker.</p>;
  }
  return (
    <table className="w-full text-left text-xs">
      <thead className="text-ink-faint">
        <tr>
          <th className="px-3 py-1.5 font-medium">Acquired</th>
          <th className="px-3 py-1.5 font-medium text-right">Qty left</th>
          <th className="px-3 py-1.5 font-medium">Tax-free on</th>
          <th className="px-3 py-1.5 font-medium text-right">Days held</th>
          <th className="px-3 py-1.5 font-medium">3y</th>
          <th className="px-3 py-1.5 font-medium text-right">Cost CZK</th>
          <th className="px-3 py-1.5 font-medium text-right">Cost USD</th>
        </tr>
      </thead>
      <tbody>
        {lots.map((lot) => (
          <tr key={lot.lot_id} className="border-t border-white/5">
            <td className="px-3 py-1.5 tabular-nums text-ink-muted">{lot.acquisition_date}</td>
            <td className="px-3 py-1.5 text-right tabular-nums">
              {formatQty(lot.quantity_remaining)}
            </td>
            <td className="px-3 py-1.5 tabular-nums">{lot.tax_free_on}</td>
            <td className="px-3 py-1.5 text-right tabular-nums text-ink-muted">
              {lot.holding_period_days}
            </td>
            <td className="px-3 py-1.5">
              {lot.qualifies_3y_exemption ? (
                <span className="rounded-md bg-ok/15 px-1.5 py-0.5 text-[10px] font-semibold text-ok">
                  3y
                </span>
              ) : (
                <span className="rounded-md bg-white/5 px-1.5 py-0.5 text-[10px] text-ink-faint">
                  pending
                </span>
              )}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">
              {formatCzk(lot.cost_basis_czk)}
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums">
              {formatUsd(lot.cost_basis_usd)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function TaxOpenLotsTable({ positions }: { positions: TaxOpenPosition[] }) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());

  const lotsByTicker = useMemo(() => {
    const map = new Map<string, TaxOpenLot[]>();
    for (const p of positions) map.set(p.ticker, lotsFor(p));
    return map;
  }, [positions]);

  function toggleTicker(ticker: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(ticker)) next.delete(ticker);
      else next.add(ticker);
      return next;
    });
  }

  if (positions.length === 0) {
    return (
      <EmptyState
        title="No open lots"
        description="Import investment statements first."
        action={
          <Link to="/upload" className="btn-primary">
            Upload statements
          </Link>
        }
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-ink-faint">
          <tr>
            <th className="px-3 py-2 font-medium">Ticker</th>
            <th className="px-3 py-2 font-medium text-right">Qty</th>
            <th className="px-3 py-2 font-medium text-right">Tax-free qty</th>
            <th className="px-3 py-2 font-medium text-right">Pending qty</th>
            <th className="px-3 py-2 font-medium text-right">Cost USD</th>
            <th className="px-3 py-2 font-medium text-right">Cost CZK</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => {
            const open = expanded.has(p.ticker);
            const lots = lotsByTicker.get(p.ticker) ?? [];
            return (
              <Fragment key={p.ticker}>
                <tr className="border-t border-white/5">
                  <td className="px-3 py-2 font-medium">
                    <button
                      type="button"
                      aria-expanded={open}
                      onClick={() => toggleTicker(p.ticker)}
                      className="text-left hover:text-brand"
                    >
                      {p.ticker}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{p.total_quantity}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-ok">
                    {p.quantity_tax_free}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-warn">
                    {p.quantity_pending}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatUsd(p.cost_basis_usd)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatCzk(p.cost_basis_czk)}
                  </td>
                </tr>
                {open ? (
                  <tr className="border-t border-white/5 bg-white/[0.02]">
                    <td colSpan={6} className="p-0">
                      <LotSubtable lots={lots} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
