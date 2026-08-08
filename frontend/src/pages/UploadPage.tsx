import { useCallback, useEffect, useState } from "react";
import { FileUp, CheckCircle2, AlertCircle, Copy, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { StatementFileRow, UploadResult } from "../api/types";
import { cn } from "../lib/cn";
import { Spinner } from "../components/Spinner";

export function UploadPage() {
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [history, setHistory] = useState<StatementFileRow[]>([]);
  const [histError, setHistError] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);

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

  const upload = useCallback(
    async (file: File) => {
      setBusy(true);
      setError(null);
      setResult(null);
      setFileName(file.name);
      setProgress(0);
      try {
        const r = await api.upload(file, setProgress);
        setResult(r);
        await loadHistory();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setBusy(false);
        setProgress(null);
      }
    },
    [loadHistory],
  );

  async function onRetry(row: StatementFileRow) {
    setRetryingId(row.id);
    setError(null);
    try {
      const r = await api.retryStatementFile(row.id);
      setResult(r);
      setFileName(row.original_filename);
      await loadHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retry failed");
    } finally {
      setRetryingId(null);
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) void upload(f);
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Upload</h1>
        <p className="text-sm text-ink-muted">
          Drop a bank or broker statement (CSV or eToro Excel .xlsx). Institution is detected
          automatically. Failed imports can be retried if the file was stored.
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
          <p className="font-semibold">Drag & drop a statement</p>
          <p className="text-sm text-ink-muted">CSV or eToro account statement (.xlsx)</p>
        </div>
        <label className="btn-primary cursor-pointer">
          {busy ? <Spinner className="border-t-slate-900" /> : null}
          Browse files
          <input
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            className="hidden"
            disabled={busy}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void upload(f);
              e.target.value = "";
            }}
          />
        </label>
        {fileName && <p className="text-xs text-ink-faint">Selected: {fileName}</p>}
        {progress !== null && (
          <div className="mt-2 w-full max-w-xs">
            <div className="mb-1 flex justify-between text-xs text-ink-muted">
              <span>Uploading</span>
              <span>{progress}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-brand transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="card flex gap-3 border-danger/30 bg-danger/10 p-4 text-sm text-danger">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <div>
            <div className="font-semibold">Upload failed</div>
            <div>{error}</div>
          </div>
        </div>
      )}

      {result && (
        <div
          className={cn(
            "card p-5",
            result.status === "already_imported"
              ? "border-warn/30 bg-warn/5"
              : result.status === "imported"
                ? "border-ok/30 bg-ok/5"
                : "border-danger/30 bg-danger/5",
          )}
        >
          <div className="mb-3 flex items-start gap-3">
            {result.status === "imported" || result.status === "already_imported" ? (
              <CheckCircle2
                className={cn(
                  "h-6 w-6 shrink-0",
                  result.status === "already_imported" ? "text-warn" : "text-ok",
                )}
              />
            ) : (
              <AlertCircle className="h-6 w-6 shrink-0 text-danger" />
            )}
            <div>
              <div className="text-lg font-semibold capitalize">
                {result.status.replaceAll("_", " ")}
              </div>
              <p className="text-sm text-ink-muted">{result.message}</p>
            </div>
          </div>

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

          <div className="mt-4 flex items-center gap-2 text-xs text-ink-faint">
            <Copy className="h-3.5 w-3.5" />
            <span className="font-mono break-all">SHA-256 {result.content_sha256}</span>
          </div>

          {result.errors?.length > 0 && (
            <ul className="mt-3 list-disc pl-5 text-sm text-danger">
              {result.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
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
        Supported: Raiffeisen CZ, Revolut expenses, Revolut stocks, Revolut crypto, eToro activity.
      </div>
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
