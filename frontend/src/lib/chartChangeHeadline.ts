/**
 * Shared headline semantics for live charts (MV books + portfolio).
 *
 * Backend (unchanged):
 * - Book Δ = last − first market value on the chart line
 * - Mark P&L = price move on qty held at window open
 * - Net capital = book − mark (residual / cash-qty effect)
 */

import type { ChartChangeMode } from "./chartChangeMode";

export const RECON_THRESHOLD_USD = 0.5;

export type ChartHeadlineInput = {
  seriesKind: "price" | "market_value" | string;
  mode: ChartChangeMode;
  changeAbs: number | null;
  changePct: number | null;
  markPnlAbs: number | null;
  markPnlPct: number | null;
  netCapitalAbs: number | null;
  reconThreshold?: number;
  /** Ticker price 1D only — vs-close / vs-open labels. MV books ignore this. */
  range?: string;
  sessionStatus?: string | null;
  /** Last RTH − 09:30; null before the bell. */
  changeRthAbs?: number | null;
  changeRthPct?: number | null;
};

export type ChartHeadlineSecondary = {
  /** The metric that is not primary (for MV charts). */
  otherAbs: number | null;
  otherPct: number | null;
  otherLabel: string;
  otherTitle: string;
  netCapitalAbs: number | null;
};

export type ChartHeadline = {
  /** Effective mode after fallbacks (price series forces price semantics). */
  effectiveMode: ChartChangeMode | "price";
  primaryAbs: number | null;
  primaryPct: number | null;
  /** Short suffix under the number, e.g. "Performance" */
  primaryLabel: string;
  primaryTitle: string;
  secondary: ChartHeadlineSecondary | null;
  /** True when user wanted Performance but mark is missing */
  performanceUnavailable: boolean;
  /** Whether mark and book differ enough to show recon */
  hasDivergence: boolean;
};

function hasMark(markPnlAbs: number | null): boolean {
  return markPnlAbs != null && Number.isFinite(markPnlAbs);
}

function isLocalDaySession(status: string | null | undefined): boolean {
  return status === "local_day" || status === "last_24h" || status === "prior_local_day";
}

function finiteOrNull(n: number | null | undefined): number | null {
  return n != null && Number.isFinite(n) ? n : null;
}

/**
 * Select primary + secondary change display for chart chrome.
 */
export function selectChartHeadline(input: ChartHeadlineInput): ChartHeadline {
  const {
    seriesKind,
    mode,
    changeAbs,
    changePct,
    markPnlAbs,
    markPnlPct,
    netCapitalAbs,
    reconThreshold = RECON_THRESHOLD_USD,
    range,
    sessionStatus,
    changeRthAbs,
    changeRthPct,
  } = input;

  const isPrice = seriesKind === "price";

  if (isPrice) {
    // Dual US-session numbers on ticker price 1D only. Crypto local-day and
    // multi-day keep a single "Price change". Stock-class / scope=all never
    // enter this branch (series_kind is market_value).
    const useSessionLabels = range === "1d" && !isLocalDaySession(sessionStatus);
    const rthAbs = finiteOrNull(changeRthAbs);
    const rthPct = finiteOrNull(changeRthPct);
    const showVsOpen = useSessionLabels && (rthAbs != null || rthPct != null);
    return {
      effectiveMode: "price",
      primaryAbs: changeAbs,
      primaryPct: changePct,
      primaryLabel: useSessionLabels ? "vs close" : "Price change",
      primaryTitle: useSessionLabels
        ? "vs close — vs prior RTH last (5m), includes pre/post"
        : "Price change over this chart window",
      secondary: showVsOpen
        ? {
            otherAbs: rthAbs,
            otherPct: rthPct,
            otherLabel: "vs open",
            otherTitle: "vs open — last RTH minus 9:30 ET (regular session only)",
            netCapitalAbs: null,
          }
        : null,
      performanceUnavailable: false,
      hasDivergence: false,
    };
  }

  const markOk = hasMark(markPnlAbs);
  const bookAbs = changeAbs;
  const bookPct = changePct;
  const hasDivergence =
    markOk &&
    bookAbs != null &&
    Math.abs((markPnlAbs as number) - bookAbs) > reconThreshold;

  // Performance requested but unavailable → book primary + note
  if (mode === "performance" && !markOk) {
    return {
      effectiveMode: "book",
      primaryAbs: bookAbs,
      primaryPct: bookPct,
      primaryLabel: "Market value Δ",
      primaryTitle:
        "Market value change (last − first on this chart). Performance (mark) unavailable for this window.",
      secondary: null,
      performanceUnavailable: true,
      hasDivergence: false,
    };
  }

  if (mode === "performance" && markOk) {
    return {
      effectiveMode: "performance",
      primaryAbs: markPnlAbs,
      primaryPct: markPnlPct,
      primaryLabel: "Performance",
      primaryTitle:
        "Price move on quantity held at chart start (excludes mid-window buys). Matches “how did holdings perform?”",
      secondary: hasDivergence
        ? {
            otherAbs: bookAbs,
            otherPct: bookPct,
            otherLabel: "Market value Δ",
            otherTitle:
              "Last − first market value on this chart (includes buys/sells changing the book)",
            netCapitalAbs,
          }
        : null,
      performanceUnavailable: false,
      hasDivergence,
    };
  }

  // Book mode
  return {
    effectiveMode: "book",
    primaryAbs: bookAbs,
    primaryPct: bookPct,
    primaryLabel: "Market value Δ",
    primaryTitle: "Last − first market value on this chart (matches the line endpoints)",
    secondary: hasDivergence
      ? {
          otherAbs: markPnlAbs,
          otherPct: markPnlPct,
          otherLabel: "Performance",
          otherTitle:
            "Price move on quantity held at chart start (excludes mid-window buys)",
          netCapitalAbs,
        }
      : null,
    performanceUnavailable: false,
    hasDivergence,
  };
}
