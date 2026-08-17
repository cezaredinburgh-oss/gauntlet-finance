import type { TaxDisposal } from "../../../api/types";
import { d } from "../../../lib/money";

export type DisposalTickerGroup = {
  ticker: string;
  rows: TaxDisposal[];
  gainCzk: number;
};

const MISSING_TICKER = "—";

function tickerKey(row: TaxDisposal): string {
  return (row.ticker || MISSING_TICKER).toUpperCase();
}

function compareGroups(a: DisposalTickerGroup, b: DisposalTickerGroup): number {
  // "—" is a missing-ticker bucket, not a name — keep it after A–Z.
  if (a.ticker === MISSING_TICKER && b.ticker !== MISSING_TICKER) return 1;
  if (b.ticker === MISSING_TICKER && a.ticker !== MISSING_TICKER) return -1;
  return a.ticker.localeCompare(b.ticker);
}

function compareRows(a: TaxDisposal, b: TaxDisposal): number {
  const byDate = a.date.localeCompare(b.date);
  if (byDate !== 0) return byDate;
  return a.id.localeCompare(b.id);
}

export function groupDisposalsByTicker(rows: TaxDisposal[]): DisposalTickerGroup[] {
  const buckets = new Map<string, TaxDisposal[]>();
  for (const row of rows) {
    const key = tickerKey(row);
    const list = buckets.get(key);
    if (list) list.push(row);
    else buckets.set(key, [row]);
  }

  const groups: DisposalTickerGroup[] = [];
  for (const [ticker, groupRows] of buckets) {
    const sorted = [...groupRows].sort(compareRows);
    let gainCzk = 0;
    for (const row of sorted) {
      gainCzk += d(row.realized_gain_czk);
    }
    groups.push({ ticker, rows: sorted, gainCzk });
  }

  groups.sort(compareGroups);
  return groups;
}
