import { useCallback, useState } from "react";
import { FileUp, CheckCircle2, AlertCircle, Copy } from "lucide-react";
import { api } from "../api/client";
import type { UploadResult } from "../api/types";
import { cn } from "../lib/cn";
import { Spinner } from "../components/Spinner";

export function UploadPage() {
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  const upload = useCallback(async (file: File) => {
    setBusy(true);
    setError(null);
    setResult(null);
    setFileName(file.name);
    setProgress(0);
    try {
      const r = await api.upload(file, setProgress);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }, []);

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) void upload(f);
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Upload</h1>
        <p className="text-sm text-ink-muted">
          Drop a bank or broker statement (CSV or eToro Excel .xlsx). Institution is detected
          automatically. Re-uploads of the same file are skipped via SHA-256.
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
        {fileName && (
          <p className="text-xs text-ink-faint">Selected: {fileName}</p>
        )}
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

      <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4 text-xs text-ink-muted">
        Supported: Raiffeisen CZ, Revolut expenses, Revolut stocks, Revolut crypto, eToro activity.
      </div>
    </div>
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
