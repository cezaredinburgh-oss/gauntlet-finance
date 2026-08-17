import type { LotSummary } from "../../../api/types";
import { Spinner } from "../../../components/Spinner";
import { cn } from "../../../lib/cn";
import { formatQty, formatUsd } from "../../../lib/money";

type OpenLot = LotSummary["lots"][number];

const LOT_COLUMNS = [
  { key: "acquired", label: "Acquired", align: "left" },
  { key: "qty", label: "Qty left", align: "right" },
  { key: "cost", label: "Cost USD", align: "right" },
  { key: "days", label: "Days held", align: "right" },
  { key: "taxFree", label: "Tax-free on", align: "left" },
  { key: "exempt", label: "3y", align: "left" },
] as const;

function sortLotsFifo(lots: OpenLot[]): OpenLot[] {
  return [...lots].sort((a, b) =>
    a.acquisition_date.localeCompare(b.acquisition_date),
  );
}

function LotsHeader() {
  return (
    <div className="border-b border-white/5 px-4 py-3">
      <h2 className="text-sm font-semibold tracking-tight">Open lots</h2>
      <p className="text-xs text-ink-faint">FIFO remaining · USD cost as stored</p>
    </div>
  );
}

function LotsTableHead() {
  return (
    <thead>
      <tr className="border-b border-white/10 text-ink-faint">
        {LOT_COLUMNS.map((col) => (
          <th
            key={col.key}
            className={cn(
              "px-2 py-2 font-medium",
              col.align === "right" ? "text-right" : "text-left",
            )}
          >
            {col.label}
          </th>
        ))}
      </tr>
    </thead>
  );
}

/**
 * Open-lot table under the frozen detail wrap. USD-only; no client 1095 math.
 */
export function HoldingsLotsSection({
  summary,
  loading,
  error,
  onRetry,
}: {
  summary: LotSummary | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const lots = summary ? sortLotsFifo(summary.lots) : [];

  return (
    <div className="card flex flex-col">
      <LotsHeader />
      {loading ? (
        <div className="overflow-x-auto" aria-busy="true" aria-live="polite">
          <table className="w-full min-w-[32rem] text-left text-xs">
            <LotsTableHead />
            <tbody className="divide-y divide-white/5">
              {Array.from({ length: 6 }, (_, i) => (
                <tr key={i} className="h-8">
                  <td colSpan={LOT_COLUMNS.length} className="px-2 py-2">
                    <div className="h-3.5 w-full rounded bg-white/[0.04]" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center justify-center gap-2 px-4 py-3 text-xs text-ink-faint">
            <Spinner className="h-4 w-4" />
            Loading lots…
          </div>
        </div>
      ) : error ? (
        <div className="flex flex-col items-center gap-3 px-4 py-8 text-center">
          <p className="text-sm text-danger">{error}</p>
          <button type="button" className="btn-secondary" onClick={onRetry}>
            Retry
          </button>
        </div>
      ) : lots.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-ink-faint">No open lots</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[32rem] text-left text-xs">
            <LotsTableHead />
            <tbody className="divide-y divide-white/5">
              {lots.map((lot) => (
                <tr key={lot.lot_id}>
                  <td className="px-2 py-2 tabular-nums text-ink-muted">
                    {lot.acquisition_date}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums">
                    {formatQty(lot.quantity_remaining)}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums">
                    {formatUsd(lot.cost_basis_usd)}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-ink-muted">
                    {lot.holding_period_days}
                  </td>
                  <td className="px-2 py-2 tabular-nums text-ink-muted">
                    {lot.tax_free_on}
                  </td>
                  <td className="px-2 py-2">
                    {lot.qualifies_3y_exemption ? (
                      <span className="badge bg-ok/15 text-ok">Yes</span>
                    ) : (
                      <span className="badge bg-warn/15 text-warn">No</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
