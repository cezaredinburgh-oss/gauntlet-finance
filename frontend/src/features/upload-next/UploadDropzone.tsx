import { useState, type DragEvent } from "react";
import { FileUp } from "lucide-react";
import { cn } from "../../lib/cn";

export const UPLOAD_ACCEPT =
  ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

export type BatchProgress = {
  index: number;
  total: number;
  fileName: string;
  /** Overall 0–100 across the whole batch */
  pct: number;
  /** Server-side import running after file accepted */
  phase?: "uploading" | "processing";
};

export function UploadDropzone({
  busy,
  batchProgress,
  onFiles,
}: {
  busy: boolean;
  batchProgress: BatchProgress | null;
  onFiles: (files: File[]) => void;
}) {
  const [drag, setDrag] = useState(false);

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    const list = e.dataTransfer.files;
    if (list?.length) onFiles(Array.from(list));
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={onDrop}
      className={cn(
        "card flex min-w-0 flex-col items-center justify-center gap-3 border-2 border-dashed px-6 py-16 text-center transition",
        drag ? "border-brand bg-brand/5" : "border-white/10",
        busy && "pointer-events-none opacity-70",
      )}
    >
      <div className="rounded-2xl bg-brand/15 p-4 text-brand">
        <FileUp className="h-8 w-8" />
      </div>
      <div className="min-w-0">
        <p className="font-semibold">Drag & drop statements</p>
        <p className="text-sm text-ink-muted">
          One or many · CSV or eToro account statement (.xlsx)
        </p>
      </div>
      <label className="btn-primary cursor-pointer">
        Browse files
        <input
          type="file"
          multiple
          accept={UPLOAD_ACCEPT}
          className="hidden"
          disabled={busy}
          onChange={(e) => {
            const list = e.target.files;
            if (list?.length) onFiles(Array.from(list));
            e.target.value = "";
          }}
        />
      </label>
      {batchProgress && (
        <div className="mt-2 w-full max-w-sm min-w-0">
          <div className="mb-1 flex justify-between gap-2 text-xs text-ink-muted">
            <span className="min-w-0 truncate" title={batchProgress.fileName}>
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
  );
}
