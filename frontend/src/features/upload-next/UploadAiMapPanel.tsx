import { Sparkles } from "lucide-react";
import { Spinner } from "../../components/Spinner";
import type { FileOutcome } from "./summarizeOutcomes";

export function outcomeNeedsAiMap(outcome: FileOutcome): boolean {
  const result = outcome.result;
  if (!result) return false;
  const ok =
    result.status === "imported" || result.status === "already_imported";
  return (
    !ok &&
    (Boolean(result.ai_map_eligible) ||
      /unrecognized statement|header scores/i.test(result.message || ""))
  );
}

export function UploadAiMapPanel({
  outcome,
  onMap,
  onImportMapped,
  onDismissMap,
}: {
  outcome: FileOutcome;
  onMap: () => void;
  onImportMapped: () => void;
  onDismissMap: () => void;
}) {
  if (!outcomeNeedsAiMap(outcome)) return null;

  const { mapPreview, mapError, mapBusy, importBusy } = outcome;

  return (
    <div className="min-w-0 space-y-3">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn-secondary inline-flex items-center gap-1 text-xs"
          disabled={mapBusy || importBusy}
          onClick={onMap}
        >
          {mapBusy ? (
            <Spinner className="h-3.5 w-3.5 border-t-brand" />
          ) : (
            <Sparkles className="h-3.5 w-3.5" />
          )}
          {mapBusy ? "Working — mapping columns" : "Map with Grok"}
        </button>
        <span className="text-[11px] text-ink-faint">
          Cash CSV only · preview before import · no account numbers sent
        </span>
      </div>
      {mapError && <p className="text-xs text-danger">{mapError}</p>}
      {mapPreview?.mapping && (
        <div className="min-w-0 space-y-2 rounded-xl border border-brand/25 bg-brand/5 p-3">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <h3 className="min-w-0 text-xs font-semibold uppercase tracking-wide text-brand">
              Proposed map · {mapPreview.mapping.institution} ·{" "}
              {(mapPreview.mapping.confidence * 100).toFixed(0)}%
            </h3>
            <button
              type="button"
              className="text-[11px] text-ink-faint hover:text-ink"
              onClick={onDismissMap}
            >
              Dismiss
            </button>
          </div>
          {mapPreview.mapping.notes && (
            <p className="min-w-0 break-words text-[11px] text-ink-muted">
              {mapPreview.mapping.notes}
            </p>
          )}
          <div className="flex min-w-0 flex-wrap gap-1.5 text-[10px] text-ink-faint">
            {Object.entries(mapPreview.mapping.columns)
              .filter(([, role]) => role !== "ignore")
              .map(([h, role]) => (
                <span
                  key={h}
                  className="rounded-md border border-white/10 bg-white/[0.03] px-1.5 py-0.5"
                >
                  {h} → {role}
                </span>
              ))}
          </div>
          {mapPreview.preview.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[11px]">
                <thead className="text-ink-faint">
                  <tr>
                    <th className="py-1 pr-2 font-medium">Date</th>
                    <th className="py-1 pr-2 font-medium">Amount</th>
                    <th className="py-1 pr-2 font-medium">Ccy</th>
                    <th className="py-1 font-medium">Merchant</th>
                  </tr>
                </thead>
                <tbody>
                  {mapPreview.preview.map((row, idx) => {
                    const merchant = row.merchant || row.description || "—";
                    return (
                      <tr key={idx} className="border-t border-white/5">
                        <td className="py-1 pr-2 tabular-nums">{row.booking_date}</td>
                        <td className="py-1 pr-2 tabular-nums">{row.amount}</td>
                        <td className="py-1 pr-2">{row.currency}</td>
                        <td
                          className="min-w-0 max-w-[12rem] break-words py-1"
                          title={merchant}
                        >
                          {merchant}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <button
            type="button"
            className="btn-primary text-xs"
            disabled={importBusy}
            onClick={onImportMapped}
          >
            {importBusy
              ? "Importing…"
              : `Import ${mapPreview.total_data_rows || "mapped"} cash rows`}
          </button>
        </div>
      )}
    </div>
  );
}
