import { useMemo, useState } from "react";
import { ChevronDown, Sparkles, X } from "lucide-react";
import type { Category } from "../../api/types";
import {
  formatVendorPreview,
  groupVendorsByCategory,
  type VendorBucket,
} from "../../lib/ruleSuggest";
import { Spinner } from "../../components/Spinner";
import { cn } from "../../lib/cn";
import type { VendorApplyRow } from "./VendorRollup";

export function GrokPlusPanel({
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
  onExpandCategory,
  onClose,
}: {
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
  onExpandCategory?: () => void;
  onClose: () => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const { groups, unassigned } = useMemo(
    () => groupVendorsByCategory(buckets),
    [buckets],
  );
  const unmatchedId = "__unmatched__";

  function chosen(b: VendorBucket): string {
    return picks[b.key] ?? b.suggestedCategoryId ?? "";
  }

  function rowsFor(vendors: VendorBucket[]): VendorApplyRow[] {
    return vendors
      .map((bucket) => ({ bucket, categoryId: chosen(bucket) }))
      .filter((row) => Boolean(row.categoryId));
  }

  function toggleCategory(id: string) {
    setOpenId((prev) => (prev === id ? null : id));
    onExpandCategory?.();
  }

  return (
    <div className="card space-y-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <span className="rounded-lg bg-brand/15 p-2 text-brand">
            <Sparkles className="h-4 w-4" />
          </span>
          <div>
            <h2 className="font-semibold">Ask Grok+</h2>
            <p className="text-sm text-ink-muted">
              Residual vendors sorted locally, then leftovers sent to Grok.
              Click a category to see vendors, then a vendor to see transactions.
              Unmatched names stay empty on purpose.
            </p>
          </div>
        </div>
        <button type="button" className="btn-ghost p-2" aria-label="Close" onClick={onClose}>
          <X className="h-4 w-4" />
        </button>
      </div>

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

      {groups.length === 0 && unassigned.length === 0 ? (
        <p className="text-sm text-ink-faint">
          {busy ? "Sorting vendors…" : "No categories matched yet."}
        </p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-white/10">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-white/5 bg-white/[0.02] text-xs uppercase tracking-wide text-ink-faint">
              <tr>
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2">Vendors</th>
                <th className="px-3 py-2 text-right">Tx</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {groups.map((g) => {
                const ready = rowsFor(g.vendors);
                const open = openId === g.categoryId;
                const preview = formatVendorPreview(g.vendors.map((v) => v.label));
                return (
                  <CategoryBlock
                    key={g.categoryId}
                    categoryName={g.categoryName}
                    preview={preview}
                    vendorCount={g.vendors.length}
                    txCount={g.txCount}
                    open={open}
                    vendors={g.vendors}
                    catsSorted={catsSorted}
                    chosen={chosen}
                    busy={busy}
                    isReadOnly={isReadOnly}
                    applyingKey={applyingKey}
                    readyCount={ready.length}
                    onToggle={() => toggleCategory(g.categoryId)}
                    onPick={(key, categoryId) =>
                      setPicks((prev) => ({ ...prev, [key]: categoryId }))
                    }
                    onApply={onApply}
                    onApplyRule={onApplyRule}
                    onApplyAll={() => onApplyAll(ready, false)}
                    onApplyAllRules={() => onApplyAll(ready, true)}
                    onOpen={onOpen}
                  />
                );
              })}
              {unassigned.length > 0 ? (
                <CategoryBlock
                  key={unmatchedId}
                  categoryName="Unmatched"
                  preview={formatVendorPreview(unassigned.map((v) => v.label))}
                  vendorCount={unassigned.length}
                  txCount={unassigned.reduce((n, v) => n + v.count, 0)}
                  open={openId === unmatchedId}
                  vendors={unassigned}
                  catsSorted={catsSorted}
                  chosen={chosen}
                  busy={busy}
                  isReadOnly={isReadOnly}
                  applyingKey={applyingKey}
                  readyCount={rowsFor(unassigned).length}
                  onToggle={() => toggleCategory(unmatchedId)}
                  onPick={(key, categoryId) =>
                    setPicks((prev) => ({ ...prev, [key]: categoryId }))
                  }
                  onApply={onApply}
                  onApplyRule={onApplyRule}
                  onApplyAll={() => onApplyAll(rowsFor(unassigned), false)}
                  onApplyAllRules={() => onApplyAll(rowsFor(unassigned), true)}
                  onOpen={onOpen}
                />
              ) : null}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CategoryBlock({
  categoryName,
  preview,
  vendorCount,
  txCount,
  open,
  vendors,
  catsSorted,
  chosen,
  busy,
  isReadOnly,
  applyingKey,
  readyCount,
  onToggle,
  onPick,
  onApply,
  onApplyRule,
  onApplyAll,
  onApplyAllRules,
  onOpen,
}: {
  categoryName: string;
  preview: string;
  vendorCount: number;
  txCount: number;
  open: boolean;
  vendors: VendorBucket[];
  catsSorted: Category[];
  chosen: (b: VendorBucket) => string;
  busy: boolean;
  isReadOnly: boolean;
  applyingKey: string | null;
  readyCount: number;
  onToggle: () => void;
  onPick: (key: string, categoryId: string) => void;
  onApply: (bucket: VendorBucket, categoryId: string) => void;
  onApplyRule: (bucket: VendorBucket, categoryId: string) => void;
  onApplyAll: () => void;
  onApplyAllRules: () => void;
  onOpen: (bucket: VendorBucket) => void;
}) {
  return (
    <>
      <tr
        className={cn(
          "cursor-pointer hover:bg-white/[0.03]",
          open && "bg-brand/5",
        )}
        onClick={onToggle}
      >
        <td className="px-3 py-3 font-medium text-ink">
          <span className="inline-flex items-center gap-1.5">
            <ChevronDown
              className={cn(
                "h-3.5 w-3.5 text-ink-muted transition",
                open ? "rotate-0" : "-rotate-90",
              )}
            />
            {categoryName}
          </span>
        </td>
        <td className="max-w-md truncate px-3 py-3 text-ink-muted" title={preview}>
          {preview}
        </td>
        <td className="whitespace-nowrap px-3 py-3 text-right text-ink-muted">
          {vendorCount} · ×{txCount}
        </td>
        <td className="px-3 py-3 text-right" onClick={(e) => e.stopPropagation()}>
          <div className="flex flex-wrap justify-end gap-1.5">
            <button
              type="button"
              className="btn-primary text-xs"
              disabled={busy || isReadOnly || readyCount === 0}
              onClick={onApplyAll}
            >
              Apply all
            </button>
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={busy || isReadOnly || readyCount === 0}
              onClick={onApplyAllRules}
            >
              Apply all + rules
            </button>
          </div>
        </td>
      </tr>
      {open && (
        <tr className="bg-black/20">
          <td colSpan={4} className="px-3 py-2">
            <ul className="divide-y divide-white/5">
              {vendors.map((b) => {
                const pick = chosen(b);
                return (
                  <li
                    key={b.key}
                    className="flex flex-wrap items-center gap-2 py-2"
                  >
                    <button
                      type="button"
                      className="min-w-0 flex-1 text-left"
                      onClick={() => onOpen(b)}
                    >
                      <span className="font-medium text-ink">{b.label}</span>
                      <span className="ml-2 text-xs text-ink-muted">×{b.count}</span>
                      {b.reason ? (
                        <span className="mt-0.5 block text-[11px] text-ink-faint">
                          {b.reason}
                        </span>
                      ) : null}
                    </button>
                    <select
                      className="input max-w-[12rem] py-1.5 text-sm"
                      value={pick}
                      disabled={busy || isReadOnly}
                      onChange={(e) => onPick(b.key, e.target.value)}
                    >
                      <option value="">Category…</option>
                      {catsSorted.map((cat) => (
                        <option key={cat.id} value={cat.id}>
                          {cat.name}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="btn-primary text-xs"
                      disabled={busy || isReadOnly || !pick}
                      onClick={() => onApply(b, pick)}
                    >
                      {applyingKey === b.key ? (
                        <Spinner className="h-3.5 w-3.5 border-t-slate-900" />
                      ) : null}
                      Apply
                    </button>
                    <button
                      type="button"
                      className="btn-secondary text-xs"
                      disabled={busy || isReadOnly || !pick}
                      onClick={() => onApplyRule(b, pick)}
                    >
                      Apply + rule
                    </button>
                  </li>
                );
              })}
            </ul>
          </td>
        </tr>
      )}
    </>
  );
}
