import type { Category, Transaction } from "../../api/types";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type TxSortKey = "date" | "description" | "category" | "source" | "amount";
export type SortDir = "asc" | "desc";

export const SORT_DEFAULT_DIR: Record<TxSortKey, SortDir> = {
  date: "desc",
  description: "asc",
  category: "asc",
  source: "asc",
  amount: "desc",
};

export function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

export function normTxId(id: string): string {
  return id.trim().toLowerCase();
}

export function txSignedAmount(t: Transaction): number {
  const raw =
    t.amount_usd != null && t.amount_usd !== "" ? t.amount_usd : t.amount;
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

export function txIsExpense(t: Transaction): boolean {
  return txSignedAmount(t) < 0;
}

export function txIsIncome(t: Transaction): boolean {
  return txSignedAmount(t) > 0;
}

export function txHasRealCategory(
  t: Transaction,
  catMap: Map<string, Category>,
): boolean {
  if (!t.category_id) return false;
  const cat = catMap.get(t.category_id);
  if (!cat) return false;
  if (cat.life_domain === "Other") return false;
  const name = (cat.name || "").trim().toLowerCase();
  if (name === "other" || name === "uncategorized") return false;
  return true;
}

export function txSortDescription(t: Transaction): string {
  return (t.merchant || t.description || "").trim();
}

export function isoDaysAgo(days: number): { from: string; to: string } {
  const to = new Date();
  const from = new Date();
  from.setDate(to.getDate() - days);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { from: iso(from), to: iso(to) };
}
