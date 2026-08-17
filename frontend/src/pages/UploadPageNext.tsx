import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle } from "lucide-react";
import { api } from "../api/client";
import type { StatementFileRow } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { UPLOAD_DESK } from "../auth/labDesk";
import { WorkingBanner } from "../components/WorkingBanner";
import { UploadDocumentCenter } from "../features/upload-next/UploadDocumentCenter";
import { UploadDropzone, type BatchProgress } from "../features/upload-next/UploadDropzone";
import {
  summarizeOutcomes,
  type FileOutcome,
} from "../features/upload-next/summarizeOutcomes";
import { LabNextChrome } from "../lab-chrome/LabNextChrome";

const MAX_BATCH_FILES = 25;

function isStatementFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return name.endsWith(".csv") || name.endsWith(".xlsx");
}

const uploadEyebrow = (
  <span className="inline-flex rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5">
    CSV / .xlsx · SHA-256 idempotent
  </span>
);

/** Lab next Upload: dropzone-first document center. Same ingest contract as classic. */
export function UploadPageNext() {
  const { isReadOnly } = useAuth();
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

  const summary = summarizeOutcomes(outcomes);
  const mapBusy = outcomes.some((o) => o.mapBusy);
  const importBusy = outcomes.some((o) => o.importBusy);
  const pageBusy = busy || mapBusy || importBusy || Boolean(retryingId);

  return (
    <LabNextChrome config={UPLOAD_DESK} label="Upload desk" eyebrow={uploadEyebrow}>
      {isReadOnly ? (
        <>
          <p className="text-sm text-ink-muted">
            Sample portfolio is read-only — statement uploads are disabled. You are
            exploring the synthetic sample portfolio. To try importing real bank
            statements, sign out and choose{" "}
            <strong className="text-ink">Try with your statements</strong> on the
            landing page.
          </p>
          <Link to="/login" className="btn-secondary inline-flex">
            Back to landing
          </Link>
        </>
      ) : (
        <>
          <UploadDropzone
            busy={busy}
            batchProgress={batchProgress}
            onFiles={(files) => void uploadMany(files)}
          />

          {pageBusy ? (
            <WorkingBanner
              title={
                mapBusy
                  ? "Working — mapping this statement"
                  : importBusy
                    ? "Working — importing mapped rows"
                    : retryingId
                      ? "Working — retrying import"
                      : "Working — importing statements"
              }
              detail={
                mapBusy
                  ? "Grok is reading column headers. This usually takes 10–30 seconds. Nothing is imported until you confirm."
                  : importBusy
                    ? "Writing cash transactions from the confirmed column map."
                    : retryingId
                      ? "Re-running the stored file through the same pipeline."
                      : "Files run one after another so SHA-256 dedupe stays correct."
              }
            />
          ) : null}

          {batchError && (
            <div className="card flex min-w-0 gap-3 border-warn/30 bg-warn/10 p-4 text-sm text-warn">
              <AlertCircle className="h-5 w-5 shrink-0" />
              <div className="min-w-0 break-words">{batchError}</div>
            </div>
          )}

          {summary && (
            <div className="min-w-0 text-sm text-ink-muted">
              <span className="font-medium text-ink">{summary.headline}</span>
              {summary.detail ? (
                <span className="text-ink-faint"> · {summary.detail}</span>
              ) : null}
            </div>
          )}

          <UploadDocumentCenter
            outcomes={outcomes}
            history={history}
            histError={histError}
            retryingId={retryingId}
            onRetry={(row) => void onRetry(row)}
            onRefreshHistory={() => void loadHistory()}
            onMap={(i) => void runAiMap(i)}
            onImportMapped={(i) => void runAiImport(i)}
            onDismissMap={(i) =>
              setOutcomes((prev) =>
                prev.map((x, j) =>
                  j === i ? { ...x, mapPreview: null, mapError: undefined } : x,
                ),
              )
            }
          />

          <div className="min-w-0 rounded-xl border border-white/5 bg-white/[0.02] p-4 text-xs text-ink-muted">
            Supported natively: Raiffeisen CZ, Revolut expenses, Revolut stocks, Revolut
            crypto, eToro activity. Unknown{" "}
            <strong className="text-ink-muted">cash CSV</strong> formats can use{" "}
            <strong className="text-ink-muted">Map with Grok</strong> (confirm preview
            before import). Multi-select up to {MAX_BATCH_FILES} files; imports run one
            after another so dedupe stays correct.
          </div>
        </>
      )}
    </LabNextChrome>
  );
}
