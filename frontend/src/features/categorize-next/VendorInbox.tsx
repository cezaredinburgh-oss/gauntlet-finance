import { useMemo, useState } from "react";
import { Store } from "lucide-react";
import type { Category } from "../../api/types";
import type { VendorBucket } from "../../lib/ruleSuggest";
import { Spinner } from "../../components/Spinner";
import { CreateCategoryInline } from "../new-et/CreateCategoryInline";

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
    <li className="flex min-w-0 flex-wrap items-center gap-2 px-3 py-2 hover:bg-white/[0.03]">
      <button
        type="button"
        className="min-w-0 flex-1 text-left"
        onClick={() => onOpen(bucket)}
      >
        <span className="block truncate font-medium text-ink" title={bucket.label}>
          {bucket.label}
        </span>
        <span className="text-xs font-semibold text-ink-muted">×{bucket.count}</span>
        {bucket.reason ? (
          <span className="mt-0.5 block break-words text-[11px] text-ink-faint">
            {bucket.reason}
          </span>
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

/** Leftover vendor inbox. Page scroll owns overflow. */
export function VendorInbox({
  buckets,
  catsSorted,
  busy,
  isReadOnly,
  applyingKey,
  onApply,
  onApplyRule,
  onApplyAll,
  onOpen,
  onCategoryCreated,
  applyProgress,
}: {
  buckets: VendorBucket[];
  catsSorted: Category[];
  busy: boolean;
  isReadOnly: boolean;
  applyingKey: string | null;
  onApply: (bucket: VendorBucket, categoryId: string) => void;
  onApplyRule: (bucket: VendorBucket, categoryId: string) => void;
  onApplyAll: (rows: VendorApplyRow[], makeRule: boolean) => void;
  onOpen: (bucket: VendorBucket) => void;
  onCategoryCreated?: (cat: Category) => void;
  applyProgress?: { current: number; total: number } | null;
}) {
  const [shown, setShown] = useState(PAGE_SIZE);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [skipped, setSkipped] = useState<Set<string>>(() => new Set());
  const remaining = useMemo(
    () => buckets.filter((b) => !skipped.has(b.key)),
    [buckets, skipped],
  );
  const visible = remaining.slice(0, shown);
  const hiddenCount = Math.max(0, remaining.length - visible.length);

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
  const totalTx = useMemo(
    () => remaining.reduce((n, b) => n + b.count, 0),
    [remaining],
  );

  return (
    <div className="card min-w-0 max-w-full space-y-3 p-4">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="rounded-lg bg-brand/15 p-2 text-brand">
          <Store className="h-4 w-4" />
        </span>
        <p className="min-w-0 flex-1 break-words text-sm text-ink-muted">
          Leftover vendors
          {remaining.length
            ? ` · ${remaining.length} · ${totalTx} tx`
            : ""}
        </p>
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

      {remaining.length === 0 ? (
        <p className="text-sm text-ink-faint">None left on this list</p>
      ) : (
        <>
          <ul className="divide-y divide-white/5 rounded-xl border border-white/10">
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
                onApply={(row, categoryId) => {
                  hideKeys([row.key]);
                  onApply(row, categoryId);
                }}
                onApplyRule={(row, categoryId) => {
                  hideKeys([row.key]);
                  onApplyRule(row, categoryId);
                }}
                onOpen={onOpen}
                onSkip={(row) => hideKeys([row.key])}
              />
            ))}
          </ul>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
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
          {hiddenCount > 0 ? (
            <button
              type="button"
              className="btn-ghost text-xs"
              onClick={() =>
                setShown((n) => n + Math.min(PAGE_SIZE, hiddenCount))
              }
            >
              Show {Math.min(PAGE_SIZE, hiddenCount)} more
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}
