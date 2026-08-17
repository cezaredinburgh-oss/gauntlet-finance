import type { AlertItem } from "../../api/types";
import { summarizeAlertBuckets } from "../dashboard/alertBuckets";

export type DomainKey = "spending" | "stocks" | "crypto";

export type DomainFilter = "all" | DomainKey;

export const DOMAIN_ORDER: DomainKey[] = ["spending", "stocks", "crypto"];

export const DOMAIN_LABELS: Record<DomainKey, string> = {
  spending: "Spending",
  stocks: "Stocks",
  crypto: "Crypto",
};

function levelRank(level: string): number {
  return level === "danger" ? 0 : level === "warn" ? 1 : level === "opportunity" ? 2 : 3;
}

/** Same per-item bucket + danger→info sort as classic AlertsPage. No digest book. */
export function groupAlertsByDomain(
  items: AlertItem[],
): Record<DomainKey, AlertItem[]> {
  const map: Record<DomainKey, AlertItem[]> = {
    spending: [],
    stocks: [],
    crypto: [],
  };
  for (const a of items) {
    const d = summarizeAlertBuckets([a]);
    if (d.crypto) map.crypto.push(a);
    else if (d.stocks) map.stocks.push(a);
    else map.spending.push(a);
  }
  for (const k of DOMAIN_ORDER) {
    map[k].sort((a, b) => levelRank(String(a.level)) - levelRank(String(b.level)));
  }
  return map;
}

/** Empty domains are omitted. Filter keeps only that key when it still has items. */
export function visibleDomains(
  grouped: Record<DomainKey, AlertItem[]>,
  filter: DomainFilter,
): DomainKey[] {
  const present = DOMAIN_ORDER.filter((k) => grouped[k].length > 0);
  if (filter === "all") return present;
  return present.filter((k) => k === filter);
}
