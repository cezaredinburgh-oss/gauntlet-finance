import { useState } from "react";
import { ChevronDown, RefreshCw } from "lucide-react";
import type { StatementFileRow } from "../../api/types";
import { cn } from "../../lib/cn";
import { Spinner } from "../../components/Spinner";
import { UploadAiMapPanel, outcomeNeedsAiMap } from "./UploadAiMapPanel";
import { thisBatchShaSet, type FileOutcome } from "./summarizeOutcomes";

export function UploadDocumentCenter({
  outcomes,
  history,
  histError,
  retryingId,
  onRetry,
  onRefreshHistory,
  onMap,
  onImportMapped,
  onDismissMap,
}: {
  outcomes: FileOutcome[];
  history: StatementFileRow[];
  histError: string | null;
  retryingId: string | null;
  onRetry: (row: StatementFileRow) => void;
  onRefreshHistory: () => void;
  onMap: (index: number) => void;
  onImportMapped: (index: number) => void;
  onDismissMap: (index: number) => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const batchShas = thisBatchShaSet(outcomes);
  const historyOnly = history.filter((row) => !batchShas.has(row.content_sha256));

  function rowKey(o: FileOutcome, i: number): string {
    return o.result?.content_sha256 || o.mapSha || `file:${i}:${o.fileName}`;
  }

  function isOpen(key: string, o: FileOutcome): boolean {
    if (Object.prototype.hasOwnProperty.call(expanded, key)) return expanded[key];
    return defaultExpanded(o);
  }

  function toggle(key: string, o: FileOutcome) {
    setExpanded((prev) => ({ ...prev, [key]: !isOpen(key, o) }));
  }

  return (
    <section className="card min-w-0 overflow-hidden">
      {outcomes.length > 0 && (
        <div className="min-w-0 border-b border-white/10">
          <div className="px-4 py-3">
            <h2 className="text-sm font-semibold">This batch</h2>
            <p className="text-xs text-ink-faint">
              SHA-256 is the primary key. Expand a row for import stats or Grok map.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-ink-faint">
                <tr>
                  <th className="px-3 py-2 font-medium">File</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Parser</th>
                  <th className="px-3 py-2 font-medium text-right">Rows</th>
                  <th className="px-3 py-2 font-medium">SHA</th>
                  <th className="px-3 py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {outcomes.map((o, i) => {
                  const key = rowKey(o, i);
                  const open = isOpen(key, o);
                  const sha = o.result?.content_sha256 || o.mapSha || "";
                  const status = o.error
                    ? "error"
                    : o.result?.status || "failed";
                  return (
                    <OutcomeRows
                      key={key}
                      outcome={o}
                      sha={sha}
                      status={status}
                      open={open}
                      onToggle={() => toggle(key, o)}
                      onMap={() => onMap(i)}
                      onImportMapped={() => onImportMapped(i)}
                      onDismissMap={() => {
                        onDismissMap(i);
                        setExpanded((prev) => ({ ...prev, [key]: false }));
                      }}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="flex min-w-0 items-center justify-between gap-2 border-b border-white/10 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Import history</h2>
          <p className="text-xs text-ink-faint">
            ERROR / PENDING can retry when file bytes were stored on this server.
            This batch’s SHAs are omitted below.
          </p>
        </div>
        <button
          type="button"
          className="btn-ghost shrink-0 text-xs"
          onClick={onRefreshHistory}
        >
          Refresh
        </button>
      </div>
      {histError && <p className="px-4 py-2 text-xs text-danger">{histError}</p>}
      {history.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-ink-muted">
          No statement files yet.
        </p>
      ) : historyOnly.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-ink-muted">
          This batch already lists the latest files.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-ink-faint">
              <tr>
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">File</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Parser</th>
                <th className="px-3 py-2 font-medium text-right">Rows</th>
                <th className="px-3 py-2 font-medium">SHA</th>
                <th className="px-3 py-2 font-medium">Notes</th>
                <th className="px-3 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {historyOnly.map((row) => (
                <tr key={row.id} className="border-t border-white/5 align-top">
                  <td className="px-3 py-2 text-xs tabular-nums text-ink-muted">
                    {(row.uploaded_at || "").replace("T", " ").slice(0, 16)}
                  </td>
                  <td className="px-3 py-2">
                    <div
                      className="min-w-0 max-w-[14rem] break-words line-clamp-2 font-medium"
                      title={row.original_filename}
                    >
                      {row.original_filename}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <StatusPill status={row.status} />
                  </td>
                  <td className="min-w-0 break-words px-3 py-2 text-xs text-ink-muted">
                    {row.parser_key || row.institution || "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-ink-muted">
                    {row.row_count ?? "—"}
                  </td>
                  <td className="min-w-0 px-3 py-2 font-mono text-[11px] break-all text-ink-faint">
                    {row.content_sha256 || "—"}
                  </td>
                  <td className="min-w-0 max-w-[16rem] break-words px-3 py-2 text-[11px] text-danger">
                    {row.notes || ""}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {row.retryable ? (
                      <button
                        type="button"
                        className="btn-secondary inline-flex text-xs"
                        disabled={retryingId === row.id}
                        onClick={() => onRetry(row)}
                      >
                        {retryingId === row.id ? (
                          <Spinner className="h-3.5 w-3.5" />
                        ) : (
                          <RefreshCw className="h-3.5 w-3.5" />
                        )}
                        Retry
                      </button>
                    ) : ["ERROR", "PENDING"].includes(row.status.toUpperCase()) ? (
                      <span className="text-[10px] text-ink-faint">Re-upload file</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function defaultExpanded(o: FileOutcome): boolean {
  if (o.error || !o.result) return true;
  if (o.mapPreview || o.mapError) return true;
  if ((o.result.errors?.length ?? 0) > 0) return true;
  return outcomeNeedsAiMap(o);
}

function OutcomeRows({
  outcome,
  sha,
  status,
  open,
  onToggle,
  onMap,
  onImportMapped,
  onDismissMap,
}: {
  outcome: FileOutcome;
  sha: string;
  status: string;
  open: boolean;
  onToggle: () => void;
  onMap: () => void;
  onImportMapped: () => void;
  onDismissMap: () => void;
}) {
  const { fileName, result, error } = outcome;
  const ok =
    result?.status === "imported" || result?.status === "already_imported";
  const warn = result?.status === "already_imported";
  const fail = Boolean(error || !result || !ok);

  return (
    <>
      <tr
        className={cn(
          "border-t border-white/5 align-top",
          warn && "bg-warn/5",
          ok && !warn && "bg-ok/5",
          fail && "bg-danger/5",
        )}
      >
        <td className="px-3 py-2">
          <div
            className="min-w-0 max-w-[16rem] break-words line-clamp-2 font-medium"
            title={fileName}
          >
            {fileName}
          </div>
        </td>
        <td className="px-3 py-2">
          <StatusPill status={status} />
        </td>
        <td className="min-w-0 break-words px-3 py-2 text-xs text-ink-muted">
          {result?.parser_key || result?.institution || "—"}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-ink-muted">
          {result?.rows_parsed ?? "—"}
        </td>
        <td className="min-w-0 px-3 py-2 font-mono text-[11px] break-all text-ink-faint">
          {sha || "—"}
        </td>
        <td className="px-3 py-2 text-right">
          <button
            type="button"
            className="inline-flex items-center gap-1 text-[11px] text-ink-faint hover:text-ink"
            aria-expanded={open}
            onClick={onToggle}
          >
            Details
            <ChevronDown
              className={cn("h-3.5 w-3.5 transition", open && "rotate-180")}
            />
          </button>
        </td>
      </tr>
      {open && (
        <tr
          className={cn(
            "align-top",
            warn && "bg-warn/5",
            ok && !warn && "bg-ok/5",
            fail && "bg-danger/5",
          )}
        >
          <td colSpan={6} className="px-3 pb-3">
            <div className="min-w-0 space-y-3 pt-1">
              {error || !result ? (
                <p className="text-sm text-danger">{error || "Upload failed"}</p>
              ) : (
                <>
                  {result.message ? (
                    <p className="min-w-0 break-words text-sm text-ink-muted">
                      {result.message}
                    </p>
                  ) : null}
                  <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
                    <Stat label="Transactions" value={String(result.transactions_written)} />
                    <Stat label="Events" value={String(result.events_written)} />
                    <Stat label="Lots" value={String(result.lots_written)} />
                    <Stat
                      label="Transfer pairs"
                      value={String(result.transfer_pairs_linked)}
                    />
                    <Stat
                      label="Tx deduped"
                      value={String(result.transactions_deduped)}
                    />
                    <Stat
                      label="Events deduped"
                      value={String(result.events_deduped)}
                    />
                  </dl>
                  {result.errors?.length > 0 && (
                    <ul className="list-disc pl-5 text-sm text-danger">
                      {result.errors.map((e) => (
                        <li key={e} className="break-words">
                          {e}
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
              <UploadAiMapPanel
                outcome={outcome}
                onMap={onMap}
                onImportMapped={onImportMapped}
                onDismissMap={onDismissMap}
              />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function StatusPill({ status }: { status: string }) {
  const s = status.toUpperCase();
  const cls =
    s === "IMPORTED"
      ? "text-ok bg-ok/15"
      : s === "ALREADY_IMPORTED" || s === "SKIPPED_DUPLICATE"
        ? "text-warn bg-warn/15"
        : s === "ERROR" || s === "FAILED"
          ? "text-danger bg-danger/15"
          : s === "PENDING"
            ? "text-brand bg-brand/15"
            : "text-ink-muted bg-white/10";
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
        cls,
      )}
    >
      {status.replaceAll("_", " ")}
    </span>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl bg-black/20 px-3 py-2">
      <dt className="text-[10px] uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="font-medium text-ink">{value}</dd>
    </div>
  );
}
