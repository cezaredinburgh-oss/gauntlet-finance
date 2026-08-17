import type { ReactNode } from "react";
import { Search, X } from "lucide-react";
import type { Category } from "../../api/types";
import { cn } from "../../lib/cn";

export function ReviewFilterChips({
  q,
  onQChange,
  dateFrom,
  dateTo,
  onDateFrom,
  onDateTo,
  currency,
  onCurrency,
  categorySelectValue,
  catsSorted,
  multiCategoryCount,
  onCategory,
  hideTransfers,
  onHideTransfers,
  expensesOnly,
  onExpensesOnly,
  incomeOnly,
  onIncomeOnly,
  lifeDomain,
  filterFlag,
  unconvertedOnly,
  onClearParam,
  onShortcutUncat30,
  onShortcutExp30,
  onShortcutUncatAll,
  onWipe,
  wipeBusy,
  isReadOnly,
  hasActiveScope,
  onClearScope,
  focusCount,
  onClearFocus,
  onSelectUncategorized,
}: {
  q: string;
  onQChange: (value: string) => void;
  dateFrom: string;
  dateTo: string;
  onDateFrom: (value: string) => void;
  onDateTo: (value: string) => void;
  currency: string;
  onCurrency: (value: string) => void;
  categorySelectValue: string;
  catsSorted: Category[];
  multiCategoryCount: number;
  onCategory: (value: string) => void;
  hideTransfers: boolean;
  onHideTransfers: (next: boolean) => void;
  expensesOnly: boolean;
  onExpensesOnly: (next: boolean) => void;
  incomeOnly: boolean;
  onIncomeOnly: (next: boolean) => void;
  lifeDomain: string;
  filterFlag: string;
  unconvertedOnly: boolean;
  onClearParam: (key: string) => void;
  onShortcutUncat30: () => void;
  onShortcutExp30: () => void;
  onShortcutUncatAll: () => void;
  onWipe: () => void;
  wipeBusy: boolean;
  isReadOnly: boolean;
  hasActiveScope: boolean;
  onClearScope: () => void;
  focusCount: number;
  onClearFocus: () => void;
  onSelectUncategorized: () => void;
}) {
  return (
    <div className="sticky top-14 z-20 min-w-0 max-w-full bg-slate-950/90 py-2 backdrop-blur-md lg:top-0">
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <label className="relative min-w-0 max-w-[14rem] flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
          <input
            className="input min-w-0 py-1.5 pl-7 text-xs"
            placeholder="Search…"
            value={q}
            onChange={(e) => onQChange(e.target.value)}
          />
        </label>
        <input
          type="date"
          className="input w-auto py-1.5 text-xs"
          value={dateFrom}
          aria-label="From"
          onChange={(e) => onDateFrom(e.target.value)}
        />
        <input
          type="date"
          className="input w-auto py-1.5 text-xs"
          value={dateTo}
          aria-label="To"
          onChange={(e) => onDateTo(e.target.value)}
        />
        <select
          className="input w-auto py-1.5 text-xs"
          value={currency}
          aria-label="Currency"
          onChange={(e) => onCurrency(e.target.value)}
        >
          <option value="">All currencies</option>
          <option value="USD">USD</option>
          <option value="CZK">CZK</option>
          <option value="EUR">EUR</option>
        </select>
        <select
          className="input w-auto max-w-[11rem] py-1.5 text-xs"
          value={categorySelectValue}
          aria-label="Category"
          onChange={(e) => onCategory(e.target.value)}
        >
          <option value="">All categories</option>
          {multiCategoryCount > 0 && (
            <option value="__multi__">
              Smaller categories ({multiCategoryCount})
            </option>
          )}
          <option value="uncategorized">Uncategorized</option>
          {catsSorted.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <ChipToggle
          pressed={hideTransfers}
          onClick={() => onHideTransfers(!hideTransfers)}
        >
          {hideTransfers ? "internals hidden" : "show internals"}
        </ChipToggle>
        <ChipToggle
          pressed={expensesOnly}
          onClick={() => onExpensesOnly(!expensesOnly)}
        >
          Expenses only
        </ChipToggle>
        <ChipToggle
          pressed={incomeOnly}
          onClick={() => onIncomeOnly(!incomeOnly)}
        >
          Income only
        </ChipToggle>
        {lifeDomain ? (
          <RemovableChip onRemove={() => onClearParam("life_domain")}>
            Domain: {lifeDomain}
          </RemovableChip>
        ) : null}
        {filterFlag === "fixed" ? (
          <RemovableChip onRemove={() => onClearParam("filter")}>
            Fixed costs
          </RemovableChip>
        ) : null}
        {filterFlag === "transfer_leak" ? (
          <RemovableChip onRemove={() => onClearParam("filter")}>
            Possible transfer leak
          </RemovableChip>
        ) : null}
        {unconvertedOnly ? (
          <RemovableChip onRemove={() => onClearParam("unconverted")}>
            Missing USD
          </RemovableChip>
        ) : null}
        <button
          type="button"
          className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
          onClick={onShortcutUncat30}
        >
          Uncategorized 30d
        </button>
        <button
          type="button"
          className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
          onClick={onShortcutExp30}
        >
          Expenses 30d
        </button>
        <button
          type="button"
          className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
          onClick={onShortcutUncatAll}
        >
          Uncategorized All
        </button>
        <button
          type="button"
          className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
          onClick={onSelectUncategorized}
        >
          Select uncategorized in view
        </button>
        {focusCount > 0 ? (
          <button
            type="button"
            className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-ink-muted hover:text-ink"
            onClick={onClearFocus}
          >
            Clear focus ({focusCount})
          </button>
        ) : null}
        {hasActiveScope ? (
          <button
            type="button"
            className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-ink-muted hover:text-ink"
            onClick={onClearScope}
          >
            <span className="inline-flex items-center gap-1">
              <X className="h-3 w-3" /> Clear filters
            </span>
          </button>
        ) : null}
        <details className="ml-auto">
          <summary className="cursor-pointer list-none rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-ink-faint hover:text-ink [&::-webkit-details-marker]:hidden">
            More
          </summary>
          <div className="mt-1">
            <button
              type="button"
              className="rounded-full border border-danger/30 px-2 py-0.5 text-[11px] text-danger hover:bg-danger/10"
              disabled={wipeBusy || isReadOnly}
              onClick={onWipe}
            >
              {wipeBusy ? "Wiping…" : "Wipe categorization"}
            </button>
          </div>
        </details>
      </div>
    </div>
  );
}

function ChipToggle({
  pressed,
  onClick,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      className={cn(
        "rounded-full border px-2 py-0.5 text-[11px]",
        pressed
          ? "border-brand/40 bg-brand/10 text-ink"
          : "border-white/10 text-ink-muted hover:border-brand/40 hover:text-ink",
      )}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function RemovableChip({
  children,
  onRemove,
}: {
  children: ReactNode;
  onRemove: () => void;
}) {
  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-ink-muted">
      <span className="min-w-0 break-words">{children}</span>
      <button
        type="button"
        className="shrink-0 text-ink-faint hover:text-ink"
        aria-label={`Clear ${children}`}
        onClick={onRemove}
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}
