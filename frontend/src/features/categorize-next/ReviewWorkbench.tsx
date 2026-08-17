import { ArrowLeftRight, ChevronDown, ChevronUp } from "lucide-react";
import type { Ref } from "react";
import type { Category, Transaction } from "../../api/types";
import { Money } from "../../components/Money";
import { Spinner } from "../../components/Spinner";
import { cn } from "../../lib/cn";
import type { SortDir, TxSortKey } from "./txView";

export function ReviewWorkbench({
  tableRef,
  filteredCount,
  total,
  hasActiveScope,
  sortedRows,
  selected,
  allFilteredSelected,
  someSelected,
  sortKey,
  sortDir,
  onToggleSort,
  catMap,
  catsSorted,
  savingId,
  isReadOnly,
  onToggleOne,
  onToggleAll,
  onOverride,
  onClearCategory,
  bulkCategoryId,
  onBulkCategoryId,
  bulkBusy,
  onApplyBulk,
  onClearSelected,
  onClearSelection,
}: {
  tableRef: Ref<HTMLDivElement>;
  filteredCount: number;
  total: number;
  hasActiveScope: boolean;
  sortedRows: Transaction[];
  selected: Set<string>;
  allFilteredSelected: boolean;
  someSelected: boolean;
  sortKey: TxSortKey;
  sortDir: SortDir;
  onToggleSort: (key: TxSortKey) => void;
  catMap: Map<string, Category>;
  catsSorted: Category[];
  savingId: string | null;
  isReadOnly: boolean;
  onToggleOne: (id: string) => void;
  onToggleAll: () => void;
  onOverride: (txId: string, categoryId: string) => void;
  onClearCategory: (txId: string) => void;
  bulkCategoryId: string;
  onBulkCategoryId: (value: string) => void;
  bulkBusy: boolean;
  onApplyBulk: () => void;
  onClearSelected: () => void;
  onClearSelection: () => void;
}) {
  return (
    <div className="min-w-0 max-w-full space-y-3">
      {someSelected ? (
        <div className="flex min-w-0 flex-col gap-3 rounded-xl border border-brand/30 bg-surface-raised/95 p-3 sm:flex-row sm:items-center">
          <div className="text-sm font-medium text-ink">{selected.size} selected</div>
          <select
            className="input max-w-xs py-2 text-sm"
            value={bulkCategoryId}
            onChange={(e) => onBulkCategoryId(e.target.value)}
          >
            <option value="">Assign category…</option>
            {catsSorted.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn-primary"
            disabled={!bulkCategoryId || bulkBusy || isReadOnly}
            onClick={onApplyBulk}
          >
            {bulkBusy ? <Spinner className="h-4 w-4 border-t-slate-900" /> : null}
            Apply to selected
          </button>
          <button
            type="button"
            className="btn-secondary text-sm"
            disabled={bulkBusy || isReadOnly || selected.size === 0}
            onClick={onClearSelected}
          >
            Clear category
          </button>
          <button type="button" className="btn-ghost text-sm" onClick={onClearSelection}>
            Clear selection
          </button>
        </div>
      ) : null}

      <div
        ref={tableRef}
        className="scroll-mt-20 text-xs text-ink-faint lg:scroll-mt-4"
      >
        {filteredCount} shown
        {total !== filteredCount ? ` · ${total} from server` : ""}
        {hasActiveScope ? " · filtered" : ""}
      </div>

      {filteredCount === 0 ? (
        <p className="text-sm text-ink-muted">No transactions match these filters.</p>
      ) : (
        <div className="card min-w-0 max-w-full">
          <div className="overflow-x-auto">
            <table className="w-full min-w-0 text-left text-sm">
              <thead className="border-b border-white/5 bg-white/[0.02] text-xs uppercase tracking-wide text-ink-faint">
                <tr>
                  <th className="w-10 px-3 py-3">
                    <input
                      type="checkbox"
                      className="rounded border-white/20"
                      checked={allFilteredSelected}
                      ref={(el) => {
                        if (el) {
                          el.indeterminate = someSelected && !allFilteredSelected;
                        }
                      }}
                      onChange={onToggleAll}
                      aria-label="Select all in view"
                    />
                  </th>
                  {(
                    [
                      ["date", "Date"],
                      ["description", "Description"],
                      ["category", "Category"],
                      ["source", "Source"],
                      ["amount", "Amount"],
                    ] as Array<[TxSortKey, string]>
                  ).map(([key, label]) => {
                    const active = sortKey === key;
                    return (
                      <th
                        key={key}
                        className={cn("px-4 py-3", key === "amount" && "text-right")}
                      >
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 hover:text-ink"
                          onClick={() => onToggleSort(key)}
                        >
                          {label}
                          {active ? (
                            sortDir === "asc" ? (
                              <ChevronUp className="h-3.5 w-3.5 shrink-0" aria-hidden />
                            ) : (
                              <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden />
                            )
                          ) : (
                            <span className="inline-block h-3.5 w-3.5 shrink-0 opacity-0" aria-hidden />
                          )}
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {sortedRows.map((t) => {
                  const cat = t.category_id ? catMap.get(t.category_id) : undefined;
                  const isSel = selected.has(t.id);
                  return (
                    <tr
                      key={t.id}
                      className={cn("hover:bg-white/[0.02]", isSel && "bg-brand/5")}
                    >
                      <td className="px-3 py-3">
                        <input
                          type="checkbox"
                          className="rounded border-white/20"
                          checked={isSel}
                          onChange={() => onToggleOne(t.id)}
                          aria-label={`Select ${t.merchant || t.description || t.id}`}
                        />
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-ink-muted">
                        {t.booking_date}
                      </td>
                      <td className="min-w-0 max-w-xs break-words px-4 py-3">
                        <div className="flex min-w-0 flex-wrap items-center gap-2">
                          <span className="min-w-0 break-words font-medium text-ink">
                            {t.merchant || t.description || "—"}
                          </span>
                          {t.is_internal_transfer && (
                            <span className="badge bg-brand/15 text-brand">
                              <ArrowLeftRight className="mr-1 h-3 w-3" />
                              Internal
                            </span>
                          )}
                          {t.category_override && (
                            <span className="badge bg-warn/15 text-warn">Recategorized</span>
                          )}
                        </div>
                        {t.description && t.merchant && (
                          <div className="break-words text-xs text-ink-faint">
                            {t.description}
                          </div>
                        )}
                      </td>
                      <td className="min-w-0 break-words px-4 py-3">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <select
                            className="input max-w-[11rem] py-1.5 text-xs"
                            value={t.category_id || ""}
                            disabled={savingId === t.id || isReadOnly}
                            onChange={(e) => onOverride(t.id, e.target.value)}
                          >
                            <option value="">Uncategorized</option>
                            {catsSorted.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))}
                          </select>
                          {(t.category_id || t.category_override) && (
                            <button
                              type="button"
                              className="btn-ghost px-1.5 py-1 text-[10px] text-ink-muted"
                              disabled={savingId === t.id || isReadOnly}
                              title="Reset to uncategorized"
                              onClick={() => onClearCategory(t.id)}
                            >
                              Reset
                            </button>
                          )}
                          {savingId === t.id && <Spinner className="h-3.5 w-3.5" />}
                        </div>
                        {cat && (
                          <div className="mt-0.5 break-words text-[10px] text-ink-faint">
                            {cat.necessity} · {cat.life_domain}
                          </div>
                        )}
                        {!t.category_id && t.suggest_reason && (
                          <div className="mt-0.5 break-words text-[10px] text-brand/80">
                            Tag: {t.suggest_reason}
                            {t.suggest_category_id
                              ? ` · ${catMap.get(t.suggest_category_id)?.name || ""}`
                              : ""}
                          </div>
                        )}
                      </td>
                      <td className="min-w-0 break-words px-4 py-3 text-ink-muted">
                        {t.source_institution}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Money
                          amount={t.amount}
                          currency={t.currency}
                          amountCzk={t.amount_czk}
                          amountUsd={t.amount_usd}
                          signed
                          align="right"
                          size="sm"
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
