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

export type TradeSegmentSpec = {
  key: string;
  /** Column on each chart row holding the segment y (null elsewhere). */
  dataKey: string;
  color: string;
};

const BUY_SEG = "#2dd4a8";
const SELL_SEG = "#f87171";
const BOTH_SEG = "#fbbf24"; // amber — buy+sell on same bar
const MAX_SEGMENTS = 24;

type RowLike = {
  buyCount?: number;
  sellCount?: number;
  mv?: number | null;
  value?: number | null;
};

export type TradeSegmentOptions = {
  yKey?: "mv" | "value";
  buyColor?: string;
  sellColor?: string;
  bothColor?: string;
  maxSegments?: number;
};

/**
 * Attach short y-series columns so Recharts can draw colored Line segments
 * only across bars that end on a buy/sell (cashflow jump on the MV curve).
 *
 * Returns the row list with `tradeSeg_N` fields and segment metadata.
 */
export function withTradeCurveSegments<T extends RowLike>(
  rows: T[],
  opts: TradeSegmentOptions = {},
): { rows: T[]; segments: TradeSegmentSpec[] } {
  const yKey = opts.yKey ?? "mv";
  const buyColor = opts.buyColor ?? BUY_SEG;
  const sellColor = opts.sellColor ?? SELL_SEG;
  const bothColor = opts.bothColor ?? BOTH_SEG;
  const maxSegments = opts.maxSegments ?? MAX_SEGMENTS;

  if (rows.length < 2) return { rows, segments: [] };

  type Cand = { i: number; color: string; absJump: number };
  const cands: Cand[] = [];
  for (let i = 1; i < rows.length; i++) {
    const bc = rows[i].buyCount ?? 0;
    const sc = rows[i].sellCount ?? 0;
    if (bc <= 0 && sc <= 0) continue;
    const y0 = Number(rows[i - 1][yKey] ?? NaN);
    const y1 = Number(rows[i][yKey] ?? NaN);
    if (!Number.isFinite(y0) || !Number.isFinite(y1)) continue;
    const color = bc > 0 && sc > 0 ? bothColor : bc > 0 ? buyColor : sellColor;
    cands.push({ i, color, absJump: Math.abs(y1 - y0) });
  }
  // Prefer largest jumps if many trades (keeps layer count bounded)
  cands.sort((a, b) => b.absJump - a.absJump);
  const picked = cands.slice(0, maxSegments).sort((a, b) => a.i - b.i);

  const segments: TradeSegmentSpec[] = [];
  const augmented = rows.map((r) => ({ ...r })) as T[];

  picked.forEach((c, n) => {
    const dataKey = `tradeSeg_${n}`;
    segments.push({ key: dataKey, dataKey, color: c.color });
    for (let j = 0; j < augmented.length; j++) {
      const y =
        j === c.i - 1 || j === c.i
          ? (Number(rows[j][yKey]) as number)
          : null;
      (augmented[j] as Record<string, unknown>)[dataKey] = y;
    }
  });

  return { rows: augmented, segments };
}
