import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Store, X } from "lucide-react";
import type { Category } from "../../api/types";
import type { VendorBucket } from "../../lib/ruleSuggest";
import { Spinner } from "../../components/Spinner";
import { CreateCategoryInline } from "./CreateCategoryInline";

const PAGE_SIZE = 10;

export type VendorApplyRow = { bucket: VendorBucket; categoryId: string };

function chosenFor(
  bucket: VendorBucket,
  picks: Record<string, string>,
): string {
  return picks[bucket.key] ?? bucket.suggestedCategoryId ?? "";
}

function VendorRow({
  bucket,
  catOptions,
  chosen,
  busy,
  isReadOnly,
  applying,
  onPick,
  onApply,
  onApplyRule,
  onOpen,
  onSkip,
}: {
  bucket: VendorBucket;
  catOptions: Category[];
  chosen: string;
  busy: boolean;
  isReadOnly: boolean;
  applying: boolean;
  onPick: (key: string, categoryId: string) => void;
  onApply: (bucket: VendorBucket, categoryId: string) => void;
  onApplyRule: (bucket: VendorBucket, categoryId: string) => void;
  onOpen: (bucket: VendorBucket) => void;
  onSkip: (bucket: VendorBucket) => void;
}) {
  return (
    <li className="flex flex-wrap items-center gap-2 px-3 py-2 hover:bg-white/[0.03]">
      <button
        type="button"
        className="min-w-0 flex-1 text-left"
        onClick={() => onOpen(bucket)}
      >
        <span className="font-medium text-ink">{bucket.label}</span>
        <span className="ml-2 text-xs font-semibold text-ink-muted">
          ×{bucket.count}
        </span>
        {bucket.reason ? (
          <span className="mt-0.5 block text-[11px] text-ink-faint">{bucket.reason}</span>
        ) : null}
      </button>
      <select
        className="input max-w-[12rem] py-1.5 text-sm"
        value={chosen}
        disabled={busy || isReadOnly}
        onChange={(e) => onPick(bucket.key, e.target.value)}
        aria-label={`Category for ${bucket.label}`}
      >
        <option value="">Category…</option>
        {catOptions.map((cat) => (
          <option key={cat.id} value={cat.id}>
            {cat.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn-primary text-xs"
        disabled={busy || isReadOnly || !chosen}
        onClick={() => onApply(bucket, chosen)}
      >
        {applying ? <Spinner className="h-3.5 w-3.5 border-t-slate-900" /> : null}
        Apply ×{bucket.count}
      </button>
      <button
        type="button"
        className="btn-secondary text-xs"
        disabled={busy || isReadOnly || !chosen}
        onClick={() => onApplyRule(bucket, chosen)}
      >
        Apply + rule
      </button>
      <button
        type="button"
        className="btn-ghost text-xs"
        disabled={busy}
        onClick={() => onSkip(bucket)}
      >
        Skip
      </button>
    </li>
  );
}

export function VendorRollup({
  title,
  subtitle,
  buckets,
  catsSorted,
  busy,
  isReadOnly,
  applyingKey,
  message,
  debugText,
  onApply,
  onApplyRule,
  onApplyAll,
  onOpen,
  onClose,
  onCategoryCreated,
  applyProgress,
}: {
  title?: string;
  subtitle?: string;
  buckets: VendorBucket[];
  catsSorted: Category[];
  busy: boolean;
  isReadOnly: boolean;
  applyingKey: string | null;
  message?: string | null;
  debugText?: string | null;
  onApply: (bucket: VendorBucket, categoryId: string) => void;
  onApplyRule: (bucket: VendorBucket, categoryId: string) => void;
  onApplyAll: (rows: VendorApplyRow[], makeRule: boolean) => void;
  onOpen: (bucket: VendorBucket) => void;
  onClose: () => void;
  onCategoryCreated?: (cat: Category) => void;
  applyProgress?: { current: number; total: number } | null;
}) {
  const [page, setPage] = useState(0);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [skipped, setSkipped] = useState<Set<string>>(() => new Set());
  const remaining = useMemo(
    () => buckets.filter((b) => !skipped.has(b.key)),
    [buckets, skipped],
  );
  const pageCount = Math.max(1, Math.ceil(remaining.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const visible = remaining.slice(
    safePage * PAGE_SIZE,
    safePage * PAGE_SIZE + PAGE_SIZE,
  );

  function hideKeys(keys: string[]) {
    setSkipped((prev) => {
      const next = new Set(prev);
      for (const k of keys) next.add(k);
      return next;
    });
    setPicks((prev) => {
      const next = { ...prev };
      for (const k of keys) delete next[k];
      return next;
    });
  }
  const readyRows = useMemo(
    () =>
      visible
        .map((bucket) => ({
          bucket,
          categoryId: chosenFor(bucket, picks),
        }))
        .filter((row) => Boolean(row.categoryId)),
    [visible, picks],
  );
  const total = useMemo(
    () => buckets.reduce((n, b) => n + b.count, 0),
    [buckets],
  );
  return (
    <div className="card space-y-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <span className="rounded-lg bg-brand/15 p-2 text-brand">
            <Store className="h-4 w-4" />
          </span>
          <div>
            <h2 className="font-semibold">{title || "Vendors"}</h2>
            <p className="text-sm text-ink-muted">
              {subtitle ||
                `Residual rows grouped by merchant. ${buckets.length} vendor${
                  buckets.length === 1 ? "" : "s"
                } · ${total} tx. Top 10 at a time.`}
            </p>
          </div>
        </div>
        <button type="button" className="btn-ghost p-2" aria-label="Close vendors" onClick={onClose}>
          <X className="h-4 w-4" />
        </button>
      </div>

      {onCategoryCreated ? (
        <CreateCategoryInline
          catsSorted={catsSorted}
          disabled={busy || isReadOnly}
          onCreated={onCategoryCreated}
        />
      ) : null}
      {applyProgress && applyProgress.total > 0 ? (
        <p className="text-[11px] text-ink-muted">
          Applying {applyProgress.current} / {applyProgress.total} vendors…
        </p>
      ) : null}
      {message ? <p className="text-sm text-ink">{message}</p> : null}
      {debugText ? (
        <details className="rounded-xl border border-white/10 bg-black/30 px-3 py-2">
          <summary className="cursor-pointer text-xs font-medium text-ink-muted">
            Vendors sent and Grok prompt
          </summary>
          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all text-[11px] text-ink-faint">
            {debugText}
          </pre>
        </details>
      ) : null}

      {remaining.length === 0 ? (
        <p className="text-sm text-ink-faint">No residual vendors on the loaded list.</p>
      ) : (
        <>
          <ul className="divide-y divide-white/5 overflow-hidden rounded-xl border border-white/10">
            {visible.map((b) => (
              <VendorRow
                key={b.key}
                bucket={b}
                catOptions={catsSorted}
                chosen={chosenFor(b, picks)}
                busy={busy}
                isReadOnly={isReadOnly}
                applying={applyingKey === b.key}
                onPick={(key, categoryId) =>
                  setPicks((prev) => ({ ...prev, [key]: categoryId }))
                }
                onApply={(b, categoryId) => {
                  hideKeys([b.key]);
                  onApply(b, categoryId);
                }}
                onApplyRule={(b, categoryId) => {
                  hideKeys([b.key]);
                  onApplyRule(b, categoryId);
                }}
                onOpen={onOpen}
                onSkip={(b) => hideKeys([b.key])}
              />
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn-primary text-xs"
              disabled={busy || isReadOnly || readyRows.length === 0}
              onClick={() => {
                hideKeys(visible.map((b) => b.key));
                onApplyAll(readyRows, false);
              }}
            >
              {busy ? <Spinner className="h-3.5 w-3.5 border-t-slate-900" /> : null}
              Apply all ({readyRows.length})
            </button>
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={busy || isReadOnly || readyRows.length === 0}
              onClick={() => {
                hideKeys(visible.map((b) => b.key));
                onApplyAll(readyRows, true);
              }}
            >
              Apply all + rules ({readyRows.length})
            </button>
            <span className="text-[11px] text-ink-faint">
              Rows without a category are skipped.
            </span>
          </div>
          {pageCount > 1 && (
            <div className="flex items-center justify-between text-xs text-ink-muted">
              <button
                type="button"
                className="btn-ghost text-xs"
                disabled={safePage === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                <ChevronLeft className="h-3.5 w-3.5" />
                Previous 10
              </button>
              <span>
                {remaining.length
                  ? `${safePage * PAGE_SIZE + 1}–${safePage * PAGE_SIZE + visible.length} of ${remaining.length}`
                  : "0"}
              </span>
              <button
                type="button"
                className="btn-ghost text-xs"
                disabled={safePage >= pageCount - 1}
                onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              >
                Next 10
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
