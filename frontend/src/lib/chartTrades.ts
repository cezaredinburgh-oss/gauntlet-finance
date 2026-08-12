import type { PriceHistoryTrade } from "../api/types";

/**
 * Group statement trades onto chart points.
 *
 * Intraday: exact timestamp match (API snaps markers to a series bar).
 * Daily: calendar-day match — one point per day, so no fan-out.
 * If the trade day is missing from the series (Yahoo hole), attach to the
 * nearest prior series day so markers never orphan.
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

/** Nearest series day on or before tradeDay; else first series day. */
export function nearestPriorDay(seriesDays: string[], tradeDay: string): string | null {
  if (!seriesDays.length) return null;
  const days = seriesDays.map((d) => d.slice(0, 10)).sort();
  let best: string | null = null;
  for (const d of days) {
    if (d <= tradeDay) best = d;
    else break;
  }
  return best ?? days[0] ?? null;
}

/**
 * Build a Map from chart point date key → trades on that point.
 * Pass series point dates so daily trades on gap days still attach.
 */
export function indexTradesByPoint(
  trades: PriceHistoryTrade[],
  intraday: boolean,
  seriesPointDates?: string[],
): Map<string, PriceHistoryTrade[]> {
  const map = new Map<string, PriceHistoryTrade[]>();
  const seriesDays =
    !intraday && seriesPointDates?.length
      ? seriesPointDates.map((d) => d.slice(0, 10))
      : null;
  const seriesSet = seriesDays ? new Set(seriesDays) : null;

  for (const tr of trades) {
    let key = intraday ? tr.date : tr.date.slice(0, 10);
    if (!intraday && seriesSet && seriesDays && !seriesSet.has(key)) {
      const snap = nearestPriorDay(seriesDays, key);
      if (!snap) continue;
      key = snap;
    }
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
