import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  FileUp,
  CheckCircle2,
  AlertCircle,
  Copy,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { api } from "../api/client";
import type {
  AiMapStatementResult,
  StatementFileRow,
  UploadResult,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { cn } from "../lib/cn";
import { Spinner } from "../components/Spinner";
import { WorkingBanner } from "../components/WorkingBanner";

const MAX_BATCH_FILES = 25;
const ACCEPT =
  ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

type FileOutcome = {
  fileName: string;
  result?: UploadResult;
  error?: string;
  /** SHA for AI map after detect failure (or re-upload path) */
  mapSha?: string;
  mapPreview?: AiMapStatementResult | null;
  mapError?: string;
  mapBusy?: boolean;
  importBusy?: boolean;
};

type BatchProgress = {
  index: number;
  total: number;
  fileName: string;
  /** Overall 0–100 across the whole batch */
  pct: number;
  /** Server-side import running after file accepted */
  phase?: "uploading" | "processing";
};

function isStatementFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return name.endsWith(".csv") || name.endsWith(".xlsx");
}

export function UploadPage() {
  const { isReadOnly } = useAuth();
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [batchProgress, setBatchProgress] = useState<BatchProgress | null>(null);
  const [outcomes, setOutcomes] = useState<FileOutcome[]>([]);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [history, setHistory] = useState<StatementFileRow[]>([]);
  const [histError, setHistError] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const inFlight = useRef(false);

  const loadHistory = useCallback(async () => {
    try {
      const r = await api.statementFiles({ limit: 40 });
      setHistory(r.items || []);
      setHistError(null);
    } catch (e) {
      setHistError(e instanceof Error ? e.message : "Could not load history");
    }
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const uploadMany = useCallback(
    async (rawFiles: File[]) => {
      if (!rawFiles.length || inFlight.current) return;

      if (rawFiles.length > MAX_BATCH_FILES) {
        setBatchError(
          `Too many files (${rawFiles.length}). Select at most ${MAX_BATCH_FILES} at a time.`,
        );
        return;
      }

      const files = rawFiles.filter(isStatementFile);
      const skipped = rawFiles.length - files.length;
      if (!files.length) {
        setBatchError("No CSV or .xlsx statement files in the selection.");
        return;
      }

      inFlight.current = true;
      setBusy(true);
      setBatchError(
        skipped > 0
          ? `Skipped ${skipped} non-statement file${skipped === 1 ? "" : "s"} (only .csv / .xlsx).`
          : null,
      );
      setOutcomes([]);
      setBatchProgress({
        index: 0,
        total: files.length,
        fileName: files[0].name,
        pct: 0,
      });

      const next: FileOutcome[] = [];
      try {
        for (let i = 0; i < files.length; i++) {
          const file = files[i];
          setBatchProgress({
            index: i,
            total: files.length,
            fileName: file.name,
            pct: Math.round((i / files.length) * 100),
          });
          try {
            const result = await api.upload(file, (filePct) => {
              setBatchProgress({
                index: i,
                total: files.length,
                fileName: file.name,
                pct: Math.round(((i + filePct / 100) / files.length) * 100),
                phase: filePct < 28 ? "uploading" : "processing",
              });
            });
            next.push({
              fileName: file.name,
              result,
              mapSha: result.content_sha256,
            });
          } catch (e) {
            next.push({
              fileName: file.name,
              error: e instanceof Error ? e.message : "Upload failed",
            });
          }
          setOutcomes([...next]);
        }
        await loadHistory();
        // Kick market quotes when investments were written so Holdings is not blank
        const needPrices = next.some(
          (o) =>
            (o.result?.lots_written ?? 0) > 0 ||
            (o.result?.events_written ?? 0) > 0,
        );
        if (needPrices) {
          window.dispatchEvent(
            new CustomEvent("prices-refresh-start", {
              detail: { reason: "upload", etaSeconds: 15 },
            }),
          );
          try {
            const r = await api.refreshPrices(true);
            window.dispatchEvent(
              new CustomEvent("prices-updated", {
                detail: {
                  quote_count: r.quote_count,
                  as_of: r.as_of,
                  soft: false,
                },
              }),
            );
          } catch {
            /* soft — holdings will soft-refresh on visit */
          } finally {
            window.dispatchEvent(new CustomEvent("prices-refresh-end"));
          }
        }
      } finally {
        inFlight.current = false;
        setBusy(false);
        setBatchProgress(null);
      }
    },
    [loadHistory],
  );

  async function onRetry(row: StatementFileRow) {
    setRetryingId(row.id);
    setBatchError(null);
    try {
      const accepted = await api.retryStatementFile(row.id);
      const r = await api.waitUploadJob(accepted.job_id);
      setOutcomes([{ fileName: row.original_filename, result: r }]);
      await loadHistory();
    } catch (e) {
      setOutcomes([
        {
          fileName: row.original_filename,
          error: e instanceof Error ? e.message : "Retry failed",
        },
      ]);
    } finally {
      setRetryingId(null);
    }
  }

  async function runAiMap(index: number) {
    const o = outcomes[index];
    if (!o) return;
    const sha = o.mapSha || o.result?.content_sha256;
    if (!sha) {
      setOutcomes((prev) =>
        prev.map((x, i) =>
          i === index
            ? { ...x, mapError: "No file fingerprint — re-upload the CSV first." }
            : x,
        ),
      );
      return;
    }
    setOutcomes((prev) =>
      prev.map((x, i) =>
        i === index ? { ...x, mapBusy: true, mapError: undefined } : x,
      ),
    );
    try {
      const map = await api.aiMapStatement({ content_sha256: sha });
      setOutcomes((prev) =>
        prev.map((x, i) =>
          i === index
            ? {
                ...x,
                mapBusy: false,
                mapPreview: map,
                mapSha: map.content_sha256 || sha,
                mapError: map.message || undefined,
              }
            : x,
        ),
      );
    } catch (e) {
      setOutcomes((prev) =>
        prev.map((x, i) =>
          i === index
            ? {
                ...x,
                mapBusy: false,
                mapError: e instanceof Error ? e.message : "Map failed",
              }
            : x,
        ),
      );
    }
  }

  async function runAiImport(index: number) {
    const o = outcomes[index];
    const map = o?.mapPreview;
    if (!o || !map?.mapping || !map.content_sha256) return;
    setOutcomes((prev) =>
      prev.map((x, i) => (i === index ? { ...x, importBusy: true } : x)),
    );
    try {
      const result = await api.aiImportMapped({
        content_sha256: map.content_sha256,
        filename: o.fileName,
        mapping: map.mapping,
        headers: map.headers,
      });
      setOutcomes((prev) =>
        prev.map((x, i) =>
          i === index
            ? {
                ...x,
                importBusy: false,
                result,
                error: undefined,
                mapPreview: null,
                mapError: undefined,
              }
            : x,
        ),
      );
      await loadHistory();
    } catch (e) {
      setOutcomes((prev) =>
        prev.map((x, i) =>
          i === index
            ? {
                ...x,
                importBusy: false,
                mapError: e instanceof Error ? e.message : "Import failed",
              }
            : x,
        ),
      );
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDrag(false);
    const list = e.dataTransfer.files;
    if (list?.length) void uploadMany(Array.from(list));
  }

  const summary = summarizeOutcomes(outcomes);

  if (isReadOnly) {
    return (
      <div className="mx-auto max-w-3xl space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Upload</h1>
          <p className="text-sm text-ink-muted">
            Sample portfolio is read-only — statement uploads are disabled.
          </p>
        </div>
        <div className="card space-y-3 p-6 text-sm text-ink-muted">
          <p>
            You are exploring the synthetic sample portfolio. To try importing real bank
            statements, sign out and choose <strong className="text-ink">Try with your statements</strong>{" "}
            on the landing page.
          </p>
          <Link to="/login" className="btn-secondary inline-flex">
            Back to landing
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Upload</h1>
        <p className="text-sm text-ink-muted">
          Drop one or more bank/broker statements (CSV or eToro Excel .xlsx). Institution is
          detected automatically for each file. Failed imports can be retried if the file was
          stored.
        </p>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        className={cn(
          "card flex flex-col items-center justify-center gap-3 border-2 border-dashed px-6 py-16 text-center transition",
          drag ? "border-brand bg-brand/5" : "border-white/10",
          busy && "pointer-events-none opacity-70",
        )}
      >
        <div className="rounded-2xl bg-brand/15 p-4 text-brand">
          <FileUp className="h-8 w-8" />
        </div>
        <div>
          <p className="font-semibold">Drag & drop statements</p>
          <p className="text-sm text-ink-muted">
            One or many · CSV or eToro account statement (.xlsx)
          </p>
        </div>
        <label className="btn-primary cursor-pointer">
          {busy ? <Spinner className="border-t-slate-900" /> : null}
          Browse files
          <input
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            disabled={busy}
            onChange={(e) => {
              const list = e.target.files;
              if (list?.length) void uploadMany(Array.from(list));
              e.target.value = "";
            }}
          />
        </label>
        {batchProgress && (
          <div className="mt-2 w-full max-w-sm">
            <div className="mb-1 flex justify-between gap-2 text-xs text-ink-muted">
              <span className="truncate">
                {batchProgress.phase === "processing" ? "Processing" : "Uploading"}{" "}
                {batchProgress.index + 1} of {batchProgress.total}
                {" · "}
                {batchProgress.fileName}
              </span>
              <span className="shrink-0 tabular-nums">{batchProgress.pct}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-brand transition-all"
                style={{ width: `${batchProgress.pct}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {batchError && (
        <div className="card flex gap-3 border-warn/30 bg-warn/10 p-4 text-sm text-warn">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <div>{batchError}</div>
        </div>
      )}

      {outcomes.length > 0 && (
        <div className="space-y-3">
          {summary && (
            <div className="card border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-ink-muted">
              <span className="font-medium text-ink">{summary.headline}</span>
              {summary.detail ? (
                <span className="text-ink-faint"> · {summary.detail}</span>
              ) : null}
            </div>
          )}
          {outcomes.map((o, i) => (
            <OutcomeCard
              key={`${i}-${o.fileName}`}
              outcome={o}
              onMap={() => void runAiMap(i)}
              onImportMapped={() => void runAiImport(i)}
              onDismissMap={() =>
                setOutcomes((prev) =>
                  prev.map((x, j) =>
                    j === i ? { ...x, mapPreview: null, mapError: undefined } : x,
                  ),
                )
              }
            />
          ))}
        </div>
      )}

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between gap-2 border-b border-white/10 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">Import history</h2>
            <p className="text-xs text-ink-faint">
              ERROR / PENDING can retry when file bytes were stored on this server.
            </p>
          </div>
          <button
            type="button"
            className="btn-ghost text-xs"
            onClick={() => void loadHistory()}
          >
            Refresh
          </button>
        </div>
        {histError && (
          <p className="px-4 py-2 text-xs text-danger">{histError}</p>
        )}
        {history.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-ink-muted">No statement files yet.</p>
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
                  <th className="px-3 py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.id} className="border-t border-white/5 align-top">
                    <td className="px-3 py-2 text-xs tabular-nums text-ink-muted">
                      {(row.uploaded_at || "").replace("T", " ").slice(0, 16)}
                    </td>
                    <td className="px-3 py-2">
                      <div className="max-w-[14rem] truncate font-medium" title={row.original_filename}>
                        {row.original_filename}
                      </div>
                      {row.notes && (
                        <div className="mt-0.5 max-w-xs text-[11px] text-danger line-clamp-2">
                          {row.notes}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <StatusPill status={row.status} />
                    </td>
                    <td className="px-3 py-2 text-xs text-ink-muted">
                      {row.parser_key || row.institution || "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink-muted">
                      {row.row_count ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {row.retryable ? (
                        <button
                          type="button"
                          className="btn-secondary inline-flex text-xs"
                          disabled={retryingId === row.id}
                          onClick={() => void onRetry(row)}
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

      <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4 text-xs text-ink-muted">
        Supported natively: Raiffeisen CZ, Revolut expenses, Revolut stocks, Revolut crypto, eToro
        activity. Unknown <strong className="text-ink-muted">cash CSV</strong> formats can use{" "}
        <strong className="text-ink-muted">Map with Grok</strong> (confirm preview before import).
        Multi-select up to {MAX_BATCH_FILES} files; imports run one after another so dedupe stays
        correct.
      </div>
    </div>
  );
}

function summarizeOutcomes(outcomes: FileOutcome[]): { headline: string; detail: string } | null {
  if (!outcomes.length) return null;
  let imported = 0;
  let already = 0;
  let failed = 0;
  let other = 0;
  let tx = 0;
  let ev = 0;
  for (const o of outcomes) {
    if (o.error || !o.result) {
      failed += 1;
      continue;
    }
    const s = o.result.status;
    if (s === "imported") imported += 1;
    else if (s === "already_imported") already += 1;
    else if (s === "error" || s === "failed") failed += 1;
    else other += 1;
    tx += o.result.transactions_written || 0;
    ev += o.result.events_written || 0;
  }
  const parts = [`${outcomes.length} file${outcomes.length === 1 ? "" : "s"}`];
  if (imported) parts.push(`${imported} imported`);
  if (already) parts.push(`${already} already imported`);
  if (failed) parts.push(`${failed} failed`);
  if (other) parts.push(`${other} other`);
  const detailParts: string[] = [];
  if (tx) detailParts.push(`${tx} new tx`);
  if (ev) detailParts.push(`${ev} new events`);
  return { headline: parts.join(" · "), detail: detailParts.join(" · ") };
}

function OutcomeCard({
  outcome,
  onMap,
  onImportMapped,
  onDismissMap,
}: {
  outcome: FileOutcome;
  onMap?: () => void;
  onImportMapped?: () => void;
  onDismissMap?: () => void;
}) {
  const { fileName, result, error, mapPreview, mapError, mapBusy, importBusy } =
    outcome;

  if (error || !result) {
    return (
      <div className="card flex gap-3 border-danger/30 bg-danger/10 p-4 text-sm text-danger">
        <AlertCircle className="h-5 w-5 shrink-0" />
        <div>
          <div className="font-semibold">{fileName}</div>
          <div className="text-danger/90">{error || "Upload failed"}</div>
        </div>
      </div>
    );
  }

  const ok =
    result.status === "imported" || result.status === "already_imported";
  const warn = result.status === "already_imported";
  const canMap =
    !ok &&
    (result.ai_map_eligible ||
      /unrecognized statement|header scores/i.test(result.message || ""));

  return (
    <div
      className={cn(
        "card p-5",
        warn
          ? "border-warn/30 bg-warn/5"
          : ok
            ? "border-ok/30 bg-ok/5"
            : "border-danger/30 bg-danger/5",
      )}
    >
      <div className="mb-3 flex items-start gap-3">
        {ok ? (
          <CheckCircle2
            className={cn("h-6 w-6 shrink-0", warn ? "text-warn" : "text-ok")}
          />
        ) : (
          <AlertCircle className="h-6 w-6 shrink-0 text-danger" />
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-ink">{fileName}</div>
          <div className="text-lg font-semibold capitalize">
            {result.status.replaceAll("_", " ")}
          </div>
          {!ok && result.message ? (
            <p className="text-sm text-ink-muted">{result.message}</p>
          ) : null}
        </div>
      </div>

      <details
        className="group mt-1"
        open={!ok || (result.errors?.length ?? 0) > 0}
      >
        <summary className="cursor-pointer list-none text-xs font-medium text-ink-faint hover:text-ink-muted [&::-webkit-details-marker]:hidden">
          <span className="inline-flex items-center gap-1">
            Import details
            <span className="text-ink-faint group-open:hidden">▸</span>
            <span className="hidden text-ink-faint group-open:inline">▾</span>
          </span>
        </summary>
        <div className="mt-3 space-y-3">
          {ok && result.message ? (
            <p className="text-sm text-ink-muted">{result.message}</p>
          ) : null}
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <Stat label="Institution" value={result.institution || "—"} />
            <Stat label="Parser" value={result.parser_key || "—"} />
            <Stat label="Rows parsed" value={String(result.rows_parsed)} />
            <Stat label="Transactions" value={String(result.transactions_written)} />
            <Stat label="Events" value={String(result.events_written)} />
            <Stat label="Lots" value={String(result.lots_written)} />
            <Stat label="Transfer pairs" value={String(result.transfer_pairs_linked)} />
            <Stat label="Tx deduped" value={String(result.transactions_deduped)} />
            <Stat label="Events deduped" value={String(result.events_deduped)} />
          </dl>
          <div className="flex items-center gap-2 text-xs text-ink-faint">
            <Copy className="h-3.5 w-3.5 shrink-0" />
            <span className="font-mono break-all">SHA-256 {result.content_sha256}</span>
          </div>
          {result.errors?.length > 0 && (
            <ul className="list-disc pl-5 text-sm text-danger">
              {result.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
        </div>
      </details>

      {canMap && (
        <div className="mt-4 space-y-3 border-t border-white/10 pt-4">
          <div className="flex flex-wrap items-center gap-2">
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
          {mapBusy ? (
            <WorkingBanner
              title="Working — mapping this statement"
              detail="Grok is reading column headers. This usually takes 10–30 seconds. Nothing is imported until you confirm."
            />
          ) : null}
          {mapError && (
            <p className="text-xs text-danger">{mapError}</p>
          )}
          {mapPreview?.mapping && (
            <div className="space-y-2 rounded-xl border border-brand/25 bg-brand/5 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-brand">
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
                <p className="text-[11px] text-ink-muted">{mapPreview.mapping.notes}</p>
              )}
              <div className="flex flex-wrap gap-1.5 text-[10px] text-ink-faint">
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
                      {mapPreview.preview.map((row, idx) => (
                        <tr key={idx} className="border-t border-white/5">
                          <td className="py-1 pr-2 tabular-nums">{row.booking_date}</td>
                          <td className="py-1 pr-2 tabular-nums">{row.amount}</td>
                          <td className="py-1 pr-2">{row.currency}</td>
                          <td className="py-1 truncate max-w-[12rem]">
                            {row.merchant || row.description || "—"}
                          </td>
                        </tr>
                      ))}
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
      )}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const s = status.toUpperCase();
  const cls =
    s === "IMPORTED"
      ? "text-ok bg-ok/15"
      : s === "ERROR"
        ? "text-danger bg-danger/15"
        : s === "PENDING"
          ? "text-brand bg-brand/15"
          : s === "SKIPPED_DUPLICATE"
            ? "text-warn bg-warn/15"
            : "text-ink-muted bg-white/10";
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase", cls)}>
      {status}
    </span>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-black/20 px-3 py-2">
      <dt className="text-[10px] uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="font-medium text-ink">{value}</dd>
    </div>
  );
}
