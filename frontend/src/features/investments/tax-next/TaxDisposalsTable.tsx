import { useMemo, useState } from "react";
import type { TaxDisposal } from "../../../api/types";
import { EmptyState } from "../../../components/Spinner";
import { cn } from "../../../lib/cn";
import { formatCzk, formatUsd } from "../../../lib/money";
import { groupDisposalsByTicker } from "./groupDisposals";

const SOURCE_ALL = "all";
const MISSING_SOURCE = "—";

function sourceLabel(source: string | null | undefined): string {
  return source && source.trim() ? source : MISSING_SOURCE;
}

function DisposalsGrid({ rows }: { rows: TaxDisposal[] }) {
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs text-ink-faint">
        <tr>
          <th className="px-3 py-2 font-medium">Date</th>
          <th className="px-3 py-2 font-medium">Ticker</th>
          <th className="px-3 py-2 font-medium text-right">Qty</th>
          <th className="px-3 py-2 font-medium text-right">Gain CZK</th>
          <th className="px-3 py-2 font-medium text-right">Gain USD</th>
          <th className="px-3 py-2 font-medium text-right">Days held</th>
          <th className="px-3 py-2 font-medium">Source</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className="border-t border-white/5">
            <td className="px-3 py-2 tabular-nums text-ink-muted">{r.date}</td>
            <td className="px-3 py-2 font-medium">{r.ticker || "—"}</td>
            <td className="px-3 py-2 text-right tabular-nums">{r.quantity ?? "—"}</td>
            <td className="px-3 py-2 text-right tabular-nums">{formatCzk(r.realized_gain_czk)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{formatUsd(r.realized_gain_usd)}</td>
            <td className="px-3 py-2 text-right tabular-nums text-ink-muted">
              {r.holding_period_days ?? "—"}
            </td>
            <td className="px-3 py-2 text-ink-faint">{r.source || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function TaxDisposalsTable({
  rows,
  emptyTitle,
  emptyDescription,
}: {
  rows: TaxDisposal[];
  emptyTitle: string;
  emptyDescription: string;
}) {
  const [grouped, setGrouped] = useState(true);
  const [sourceFilter, setSourceFilter] = useState(SOURCE_ALL);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());

  const sourceOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) set.add(sourceLabel(row.source));
    return Array.from(set).sort((a, b) => {
      if (a === MISSING_SOURCE && b !== MISSING_SOURCE) return 1;
      if (b === MISSING_SOURCE && a !== MISSING_SOURCE) return -1;
      return a.localeCompare(b);
    });
  }, [rows]);

  const filtered = useMemo(() => {
    if (sourceFilter === SOURCE_ALL) return rows;
    return rows.filter((row) => sourceLabel(row.source) === sourceFilter);
  }, [rows, sourceFilter]);

  const groups = useMemo(() => groupDisposalsByTicker(filtered), [filtered]);

  function toggleTicker(ticker: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(ticker)) next.delete(ticker);
      else next.add(ticker);
      return next;
    });
  }

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-white/10 px-3 py-2">
        <div className="flex gap-1" role="group" aria-label="Disposal view">
          <button
            type="button"
            className={cn(
              "rounded-lg px-3 py-1.5 text-xs font-semibold",
              grouped
                ? "bg-brand/20 text-brand"
                : "text-ink-muted hover:text-ink",
            )}
            aria-pressed={grouped}
            onClick={() => setGrouped(true)}
          >
            Grouped
          </button>
          <button
            type="button"
            className={cn(
              "rounded-lg px-3 py-1.5 text-xs font-semibold",
              !grouped
                ? "bg-brand/20 text-brand"
                : "text-ink-muted hover:text-ink",
            )}
            aria-pressed={!grouped}
            onClick={() => setGrouped(false)}
          >
            All rows
          </button>
        </div>
        <label className="flex flex-col gap-0.5 text-[10px] uppercase tracking-wide text-ink-faint">
          Source
          <select
            className="input min-w-[8rem] py-1 text-xs normal-case"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
          >
            <option value={SOURCE_ALL}>All</option>
            {sourceOptions.map((src) => (
              <option key={src} value={src}>
                {src}
              </option>
            ))}
          </select>
        </label>
      </div>

      {filtered.length === 0 ? (
        <EmptyState title={emptyTitle} description={emptyDescription} />
      ) : grouped ? (
        <div>
          {groups.map((group) => {
            const open = expanded.has(group.ticker);
            return (
              <div key={group.ticker} className="border-t border-white/5">
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => toggleTicker(group.ticker)}
                  className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-white/[0.02]"
                >
                  <span className="font-medium">
                    {group.ticker} · {group.rows.length} rows · {formatCzk(group.gainCzk)}
                  </span>
                </button>
                {open ? (
                  <div className="overflow-x-auto">
                    <DisposalsGrid rows={group.rows} />
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <DisposalsGrid rows={filtered} />
        </div>
      )}
    </div>
  );
}
