import type { PriceHistoryTrade } from "../api/types";

/**
 * Group statement trades onto chart points.
 *
 * Intraday: exact timestamp match (API snaps markers to a series bar).
 * Daily: calendar-day match — one point per day, so no fan-out.
 *
 * Never attach a day-level trade to every 5m bar of that day.
 */
export function tradesByPointDate(
  trades: PriceHistoryTrade[],
  pointDate: string,
  intraday: boolean,
): PriceHistoryTrade[] {
  if (!trades.length) return [];
  if (intraday) {
    return trades.filter((tr) => tr.date === pointDate);
  }
  const day = pointDate.slice(0, 10);
  return trades.filter((tr) => tr.date.slice(0, 10) === day);
}

/** Build a Map from chart point date key → trades on that point. */
export function indexTradesByPoint(
  trades: PriceHistoryTrade[],
  intraday: boolean,
): Map<string, PriceHistoryTrade[]> {
  const map = new Map<string, PriceHistoryTrade[]>();
  for (const tr of trades) {
    const key = intraday ? tr.date : tr.date.slice(0, 10);
    const list = map.get(key) ?? [];
    list.push(tr);
    map.set(key, list);
  }
  return map;
}

export function tradesForPoint(
  byKey: Map<string, PriceHistoryTrade[]>,
  pointDate: string,
  intraday: boolean,
): PriceHistoryTrade[] {
  const key = intraday ? pointDate : pointDate.slice(0, 10);
  return byKey.get(key) ?? [];
}
