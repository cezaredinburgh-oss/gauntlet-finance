import { useMemo, type Dispatch, type SetStateAction } from "react";
import { ChevronDown, Sparkles } from "lucide-react";
import type { Category } from "../../api/types";
import {
  applyVendorCategoryOverrides,
  formatVendorPreview,
  groupVendorsByCategory,
  type VendorBucket,
} from "../../lib/ruleSuggest";
import { Spinner } from "../../components/Spinner";
import { cn } from "../../lib/cn";
import { CreateCategoryInline } from "../new-et/CreateCategoryInline";
import { GrokPlusStatus } from "../new-et/GrokPlusStatus";
import type { VendorApplyRow } from "./VendorInbox";

const UNMATCHED_ID = "__unmatched__";

export function GrokPlusPanelNext({
  buckets,
  catsSorted,
  busy,
  isReadOnly,
  applyingKey,
  message,
  onApply,
  onApplyRule,
  onApplyAll,
  onOpen,
  onOpenGroup,
  onExpandCategory,
  onCategoryCreated,
  coachNote,
  applyProgress,
  remaps,
  setRemaps,
  ticked,
  setTicked,
  openId,
  setOpenId,
}: {
  buckets: VendorBucket[];
  catsSorted: Category[];
  busy: boolean;
  isReadOnly: boolean;
  applyingKey: string | null;
  message?: string | null;
  onApply: (bucket: VendorBucket, categoryId: string) => void;
  onApplyRule: (bucket: VendorBucket, categoryId: string) => void;
  onApplyAll: (rows: VendorApplyRow[], makeRule: boolean) => void;
  onOpen: (bucket: VendorBucket) => void;
  onOpenGroup: (ids: string[]) => void;
  onExpandCategory?: () => void;
  onCategoryCreated?: (cat: Category) => void;
  coachNote?: string | null;
  applyProgress?: { current: number; total: number } | null;
  remaps: Record<string, string>;
  setRemaps: Dispatch<SetStateAction<Record<string, string>>>;
  ticked: Record<string, boolean>;
  setTicked: Dispatch<SetStateAction<Record<string, boolean>>>;
  openId: string | null;
  setOpenId: Dispatch<SetStateAction<string | null>>;
}) {
  const displayBuckets = useMemo(
    () => applyVendorCategoryOverrides(buckets, remaps, catsSorted),
    [buckets, remaps, catsSorted],
  );
  const { groups, unassigned } = useMemo(
    () => groupVendorsByCategory(displayBuckets),
    [displayBuckets],
  );

  function chosen(b: VendorBucket): string {
    return remaps[b.key] ?? b.suggestedCategoryId ?? "";
  }

  function isTicked(id: string, unmatched = false): boolean {
    if (id in ticked) return ticked[id];
    return !unmatched;
  }

  function setVendorCategory(keys: string[], categoryId: string) {
    setRemaps((prev) => {
      const next = { ...prev };
      for (const key of keys) next[key] = categoryId;
      return next;
    });
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

  function selectedRows(): VendorApplyRow[] {
    const rows: VendorApplyRow[] = [];
    for (const g of groups) {
      if (!isTicked(g.categoryId)) continue;
      rows.push(...rowsFor(g.vendors));
    }
    if (isTicked(UNMATCHED_ID, true)) rows.push(...rowsFor(unassigned));
    return rows;
  }

  const approveRows = selectedRows();
  const tickedGroupCount =
    groups.filter((g) => isTicked(g.categoryId)).length +
    (unassigned.length && isTicked(UNMATCHED_ID, true) ? 1 : 0);

  return (
    <div className="card min-w-0 max-w-full space-y-3 p-4">
      <div className="flex min-w-0 items-start gap-2">
        <span className="rounded-lg bg-brand/15 p-2 text-brand">
          <Sparkles className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="font-semibold">Ask Grok+</p>
          <p className="break-words text-sm text-ink-muted">
            Expand a category and click a vendor to check the txs. Retarget
            misses or add a category if the catalog is wrong, then approve.
          </p>
        </div>
      </div>
      <GrokPlusStatus variant="embedded" />
      {coachNote ? (
        <p className="rounded-lg border border-brand/20 bg-brand/10 px-3 py-2 text-xs text-ink">
          {coachNote}
        </p>
      ) : null}
      {onCategoryCreated ? (
        <CreateCategoryInline
          catsSorted={catsSorted}
          disabled={busy || isReadOnly}
          onCreated={onCategoryCreated}
        />
      ) : null}
      {applyProgress && applyProgress.total > 0 ? (
        <div>
          <p className="text-[11px] text-ink-muted">
            Applying {applyProgress.current} / {applyProgress.total} vendors…
          </p>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full bg-brand"
              style={{
                width: `${Math.min(100, (applyProgress.current / applyProgress.total) * 100)}%`,
              }}
            />
          </div>
        </div>
      ) : null}

      {message ? <p className="break-words text-sm text-ink">{message}</p> : null}

      {groups.length === 0 && unassigned.length === 0 ? (
        <p className="text-sm text-ink-faint">
          {busy
            ? "Still working — leftover vendors will land in this list."
            : "No categories matched yet. Use Ask Grok+ to start leftover matching."}
        </p>
      ) : (
        <>
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-ink-muted">
              {tickedGroupCount} group{tickedGroupCount === 1 ? "" : "s"} selected
              {approveRows.length
                ? ` · ${approveRows.length} vendor${approveRows.length === 1 ? "" : "s"} ready`
                : ""}
            </p>
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                className="btn-primary text-sm"
                disabled={busy || isReadOnly || approveRows.length === 0}
                onClick={() => onApplyAll(approveRows, false)}
              >
                Approve selected
              </button>
              <button
                type="button"
                className="btn-secondary text-sm"
                disabled={busy || isReadOnly || approveRows.length === 0}
                onClick={() => onApplyAll(approveRows, true)}
              >
                Approve selected + rules
              </button>
            </div>
          </div>
          <div className="overflow-x-auto rounded-xl border border-white/10">
            <table className="w-full min-w-0 text-left text-sm">
              <thead className="border-b border-white/5 bg-white/[0.02] text-xs uppercase tracking-wide text-ink-faint">
                <tr>
                  <th className="w-10 px-3 py-2">
                    <span className="sr-only">Include</span>
                  </th>
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
                      categoryId={g.categoryId}
                      categoryName={g.categoryName}
                      preview={preview}
                      vendorCount={g.vendors.length}
                      txCount={g.txCount}
                      open={open}
                      ticked={isTicked(g.categoryId)}
                      vendors={g.vendors}
                      catsSorted={catsSorted}
                      chosen={chosen}
                      busy={busy}
                      isReadOnly={isReadOnly}
                      applyingKey={applyingKey}
                      readyCount={ready.length}
                      onToggleTick={() =>
                        setTicked((prev) => ({
                          ...prev,
                          [g.categoryId]: !isTicked(g.categoryId),
                        }))
                      }
                      onToggle={() => toggleCategory(g.categoryId)}
                      onRemapGroup={(categoryId) =>
                        setVendorCategory(
                          g.vendors.map((v) => v.key),
                          categoryId,
                        )
                      }
                      onPick={(key, categoryId) => setVendorCategory([key], categoryId)}
                      onApply={onApply}
                      onApplyRule={onApplyRule}
                      onApplyAll={() => onApplyAll(ready, false)}
                      onApplyAllRules={() => onApplyAll(ready, true)}
                      onOpen={onOpen}
                      onOpenGroup={onOpenGroup}
                    />
                  );
                })}
                {unassigned.length > 0 ? (
                  <CategoryBlock
                    key={UNMATCHED_ID}
                    categoryId=""
                    categoryName="Unmatched"
                    preview={formatVendorPreview(unassigned.map((v) => v.label))}
                    vendorCount={unassigned.length}
                    txCount={unassigned.reduce((n, v) => n + v.count, 0)}
                    open={openId === UNMATCHED_ID}
                    ticked={isTicked(UNMATCHED_ID, true)}
                    vendors={unassigned}
                    catsSorted={catsSorted}
                    chosen={chosen}
                    busy={busy}
                    isReadOnly={isReadOnly}
                    applyingKey={applyingKey}
                    readyCount={rowsFor(unassigned).length}
                    onToggleTick={() =>
                      setTicked((prev) => ({
                        ...prev,
                        [UNMATCHED_ID]: !isTicked(UNMATCHED_ID, true),
                      }))
                    }
                    onToggle={() => toggleCategory(UNMATCHED_ID)}
                    onRemapGroup={(categoryId) =>
                      setVendorCategory(
                        unassigned.map((v) => v.key),
                        categoryId,
                      )
                    }
                    onPick={(key, categoryId) => setVendorCategory([key], categoryId)}
                    onApply={onApply}
                    onApplyRule={onApplyRule}
                    onApplyAll={() => onApplyAll(rowsFor(unassigned), false)}
                    onApplyAllRules={() => onApplyAll(rowsFor(unassigned), true)}
                    onOpen={onOpen}
                    onOpenGroup={onOpenGroup}
                  />
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function CategoryBlock({
  categoryId,
  categoryName,
  preview,
  vendorCount,
  txCount,
  open,
  ticked,
  vendors,
  catsSorted,
  chosen,
  busy,
  isReadOnly,
  applyingKey,
  readyCount,
  onToggleTick,
  onToggle,
  onRemapGroup,
  onPick,
  onApply,
  onApplyRule,
  onApplyAll,
  onApplyAllRules,
  onOpen,
  onOpenGroup,
}: {
  categoryId: string;
  categoryName: string;
  preview: string;
  vendorCount: number;
  txCount: number;
  open: boolean;
  ticked: boolean;
  vendors: VendorBucket[];
  catsSorted: Category[];
  chosen: (b: VendorBucket) => string;
  busy: boolean;
  isReadOnly: boolean;
  applyingKey: string | null;
  readyCount: number;
  onToggleTick: () => void;
  onToggle: () => void;
  onRemapGroup: (categoryId: string) => void;
  onPick: (key: string, categoryId: string) => void;
  onApply: (bucket: VendorBucket, categoryId: string) => void;
  onApplyRule: (bucket: VendorBucket, categoryId: string) => void;
  onApplyAll: () => void;
  onApplyAllRules: () => void;
  onOpen: (bucket: VendorBucket) => void;
  onOpenGroup: (ids: string[]) => void;
}) {
  const groupIds = vendors.flatMap((v) => v.ids);
  return (
    <>
      <tr
        className={cn(
          open && "bg-brand/5",
          !ticked && "opacity-60",
        )}
      >
        <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            className="h-4 w-4 accent-brand"
            checked={ticked}
            disabled={busy || isReadOnly}
            aria-label={`Include ${categoryName}`}
            onChange={onToggleTick}
          />
        </td>
        <td className="min-w-0 px-3 py-3 font-medium text-ink">
          <span className="inline-flex min-w-0 items-center gap-1.5">
            <button
              type="button"
              className="shrink-0 rounded p-0.5 text-ink-muted hover:text-ink"
              aria-expanded={open}
              aria-label={open ? `Collapse ${categoryName}` : `Expand ${categoryName}`}
              onClick={(e) => {
                e.stopPropagation();
                onToggle();
              }}
            >
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 transition",
                  open ? "rotate-0" : "-rotate-90",
                )}
              />
            </button>
            <select
              className="input max-w-[14rem] py-1.5 text-sm"
              value={categoryId}
              disabled={busy || isReadOnly}
              aria-label={`Category for ${categoryName}`}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => {
                e.stopPropagation();
                onRemapGroup(e.target.value);
              }}
            >
              <option value="">Unmatched</option>
              {catsSorted.map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {cat.name}
                </option>
              ))}
            </select>
          </span>
        </td>
        <td className="min-w-0 max-w-md truncate px-3 py-3 text-ink-muted" title={preview}>
          {preview}
        </td>
        <td className="whitespace-nowrap px-3 py-3 text-right">
          <button
            type="button"
            className="text-ink-muted hover:text-ink hover:underline"
            onClick={(e) => {
              e.stopPropagation();
              onOpenGroup(groupIds);
            }}
          >
            {vendorCount} · ×{txCount}
          </button>
        </td>
        <td className="px-3 py-3 text-right" onClick={(e) => e.stopPropagation()}>
          <div className="flex flex-wrap justify-end gap-1.5">
            <button
              type="button"
              className="btn-primary text-xs"
              disabled={busy || isReadOnly || readyCount === 0}
              onClick={(e) => {
                e.stopPropagation();
                onApplyAll();
              }}
            >
              Apply all
            </button>
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={busy || isReadOnly || readyCount === 0}
              onClick={(e) => {
                e.stopPropagation();
                onApplyAllRules();
              }}
            >
              Apply all + rules
            </button>
          </div>
        </td>
      </tr>
      {open && (
        <tr className="bg-black/20">
          <td colSpan={5} className="px-3 py-2">
            <ul className="divide-y divide-white/5">
              {vendors.map((b) => {
                const pick = chosen(b);
                return (
                  <li
                    key={b.key}
                    className="flex min-w-0 flex-wrap items-center gap-2 py-2"
                  >
                    <button
                      type="button"
                      className="min-w-0 flex-1 text-left"
                      onClick={() => onOpen(b)}
                    >
                      <span className="block truncate font-medium text-ink" title={b.label}>
                        {b.label}
                      </span>
                      <span className="text-xs text-ink-muted">×{b.count}</span>
                      {b.reason ? (
                        <span className="mt-0.5 block break-words text-[11px] text-ink-faint">
                          {b.reason}
                        </span>
                      ) : null}
                    </button>
                    <select
                      className="input max-w-[12rem] py-1.5 text-sm"
                      value={pick}
                      disabled={busy || isReadOnly}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => {
                        e.stopPropagation();
                        onPick(b.key, e.target.value);
                      }}
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
                      onClick={(e) => {
                        e.stopPropagation();
                        onApply(b, pick);
                      }}
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
                      onClick={(e) => {
                        e.stopPropagation();
                        onApplyRule(b, pick);
                      }}
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
