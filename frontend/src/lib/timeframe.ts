import {
  format,
  startOfMonth,
  startOfYear,
  subDays,
  subMonths,
  subYears,
  endOfMonth,
  endOfYear,
  addMonths,
  isSameMonth,
  parseISO,
} from "date-fns";
import type { PeriodKey } from "../api/types";

export type TimeframeValue = {
  key: PeriodKey;
  from: string | null;
  to: string;
  label: string;
};

/** Resolve a full calendar month (past months = full month; current = 1st → today). */
export function resolveCalendarMonth(year: number, monthIndex0: number): TimeframeValue {
  const now = new Date();
  const monthStart = new Date(year, monthIndex0, 1);
  const isCurrent = isSameMonth(monthStart, now);
  const from = format(startOfMonth(monthStart), "yyyy-MM-dd");
  const to = isCurrent
    ? format(now, "yyyy-MM-dd")
    : format(endOfMonth(monthStart), "yyyy-MM-dd");
  return {
    key: "calendar_month",
    from,
    to,
    label: format(monthStart, "MMMM yyyy"),
  };
}

/** Shift calendar month by deltaMonths; clamps forward so you cannot go past current month. */
export function shiftCalendarMonth(value: TimeframeValue, deltaMonths: number): TimeframeValue {
  const base = value.from ? parseISO(value.from) : new Date();
  const shifted = addMonths(startOfMonth(base), deltaMonths);
  const now = new Date();
  // Do not allow navigating into the future
  if (shifted > startOfMonth(now)) {
    return resolveCalendarMonth(now.getFullYear(), now.getMonth());
  }
  return resolveCalendarMonth(shifted.getFullYear(), shifted.getMonth());
}

/** Month shown in the stepper (from selected range start, or today). */
export function monthAnchorFromValue(value: TimeframeValue): Date {
  if (value.from) return startOfMonth(parseISO(value.from));
  return startOfMonth(new Date());
}

export function canGoNextMonth(value: TimeframeValue): boolean {
  const anchor = monthAnchorFromValue(value);
  return !isSameMonth(anchor, new Date());
}

export function isMonthStyleKey(key: PeriodKey): boolean {
  return key === "this_month" || key === "last_month" || key === "calendar_month";
}

export function resolveTimeframe(
  key: PeriodKey,
  customFrom?: string,
  customTo?: string,
): TimeframeValue {
  const now = new Date();
  const toStr = format(now, "yyyy-MM-dd");

  if (key === "this_month") {
    return {
      key,
      from: format(startOfMonth(now), "yyyy-MM-dd"),
      to: toStr,
      label: format(now, "MMMM yyyy"),
    };
  }
  if (key === "last_month") {
    const prev = subMonths(now, 1);
    return {
      key,
      from: format(startOfMonth(prev), "yyyy-MM-dd"),
      to: format(endOfMonth(prev), "yyyy-MM-dd"),
      label: format(prev, "MMMM yyyy"),
    };
  }
  if (key === "calendar_month") {
    // Fallback: current month if used without year/month
    return resolveCalendarMonth(now.getFullYear(), now.getMonth());
  }
  if (key === "last_30d") {
    return { key, from: format(subDays(now, 29), "yyyy-MM-dd"), to: toStr, label: "Last 30 days" };
  }
  if (key === "last_6m") {
    return { key, from: format(subDays(now, 179), "yyyy-MM-dd"), to: toStr, label: "Last 6 months" };
  }
  if (key === "this_year") {
    return {
      key,
      from: format(startOfYear(now), "yyyy-MM-dd"),
      to: toStr,
      label: `YTD ${now.getFullYear()}`,
    };
  }
  if (key === "last_year") {
    const y = subYears(now, 1);
    return {
      key,
      from: format(startOfYear(y), "yyyy-MM-dd"),
      to: format(endOfYear(y), "yyyy-MM-dd"),
      label: String(y.getFullYear()),
    };
  }
  if (key === "all_time") {
    return { key, from: null, to: toStr, label: "All time" };
  }
  const from = customFrom || format(startOfMonth(now), "yyyy-MM-dd");
  const to = customTo || toStr;
  return { key: "custom", from, to, label: `${from} → ${to}` };
}

export function defaultTimeframe(): TimeframeValue {
  return resolveTimeframe("this_month");
}

const TF_STORAGE_KEY = "collective.dashboard.timeframe";
const SPENDING_TF_KEY = "collective.spending.timeframe";

function loadTimeframeFromKey(storageKey: string): TimeframeValue {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) {
      // Migrate old dashboard key → spending if present
      if (storageKey === SPENDING_TF_KEY) {
        const legacy = localStorage.getItem(TF_STORAGE_KEY);
        if (legacy) {
          localStorage.setItem(SPENDING_TF_KEY, legacy);
          return loadTimeframeFromKey(SPENDING_TF_KEY);
        }
      }
      return defaultTimeframe();
    }
    const parsed = JSON.parse(raw) as Partial<TimeframeValue>;
    if (!parsed?.key) return defaultTimeframe();
    if (parsed.key === "custom" || parsed.key === "calendar_month") {
      if (parsed.from && parsed.to) {
        return {
          key: parsed.key,
          from: parsed.from,
          to: parsed.to,
          label: parsed.label || `${parsed.from} → ${parsed.to}`,
        };
      }
    }
    return resolveTimeframe(
      parsed.key as PeriodKey,
      parsed.from ?? undefined,
      parsed.to ?? undefined,
    );
  } catch {
    return defaultTimeframe();
  }
}

function saveTimeframeToKey(storageKey: string, value: TimeframeValue): void {
  try {
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        key: value.key,
        from: value.from,
        to: value.to,
        label: value.label,
      }),
    );
  } catch {
    /* ignore */
  }
}

/** @deprecated use loadStoredSpendingTimeframe for cash analysis */
export function loadStoredTimeframe(): TimeframeValue {
  return loadTimeframeFromKey(TF_STORAGE_KEY);
}

/** @deprecated use saveStoredSpendingTimeframe */
export function saveStoredTimeframe(value: TimeframeValue): void {
  saveTimeframeToKey(TF_STORAGE_KEY, value);
}

export function loadStoredSpendingTimeframe(): TimeframeValue {
  return loadTimeframeFromKey(SPENDING_TF_KEY);
}

export function saveStoredSpendingTimeframe(value: TimeframeValue): void {
  saveTimeframeToKey(SPENDING_TF_KEY, value);
}
