import { d } from "../../../lib/money";

export type CashflowRow = {
  month: string;
  bought_usd: string;
  sold_usd: string;
};

export type CashflowMonthsPref = "6" | "12" | "24" | "all";

export const CASHFLOW_MONTHS_KEY = "gauntlet.investments.cashflow.months";

export type NetSecurityCash = {
  invested: number;
  proceeds: number;
  /** bought − sold (cash deployed) */
  netDeployed: number;
};

export function loadCashflowMonthsPref(
  storage: Pick<Storage, "getItem"> = window.localStorage,
): CashflowMonthsPref {
  try {
    const raw = storage.getItem(CASHFLOW_MONTHS_KEY);
    if (raw === "6" || raw === "12" || raw === "24" || raw === "all") return raw;
  } catch {
    /* ignore */
  }
  return "24";
}

export function saveCashflowMonthsPref(
  pref: CashflowMonthsPref,
  storage: Pick<Storage, "setItem"> = window.localStorage,
): void {
  try {
    storage.setItem(CASHFLOW_MONTHS_KEY, pref);
  } catch {
    /* ignore */
  }
}

export function sliceCashflowWindow(
  rows: CashflowRow[],
  pref: CashflowMonthsPref,
): CashflowRow[] {
  if (pref === "all") return rows;
  return rows.slice(-Number(pref));
}

export function cashflowWindowCaption(pref: CashflowMonthsPref): string {
  return pref === "all" ? "all" : `last ${pref}m`;
}

/** Display-boundary totals. Net is always bought − sold. */
export function netSecurityCashUsd(rows: CashflowRow[]): NetSecurityCash {
  let invested = 0;
  let proceeds = 0;
  for (const row of rows) {
    invested += d(row.bought_usd);
    proceeds += d(row.sold_usd);
  }
  return {
    invested,
    proceeds,
    netDeployed: invested - proceeds,
  };
}
