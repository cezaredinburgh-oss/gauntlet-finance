/**
 * Recharts scatter shapes for statement buy/sell markers.
 *
 * - Buy: green triangle up · Sell: red triangle down
 * - When both sides on the same bar: vertical pixel split so neither is hidden
 * - Count ≥ 2: small badge on the glyph
 */

export const BUY_COLOR = "#2dd4a8";
export const SELL_COLOR = "#f87171";

const MARKER_SPLIT_PX = 7;
const TRI_SIZE = 6;

export type TradeMarkerPayload = {
  buyMark?: number | null;
  sellMark?: number | null;
  buyCount?: number;
  sellCount?: number;
};

type ScatterShapeProps = {
  cx?: number;
  cy?: number;
  payload?: TradeMarkerPayload;
};

function asShapeProps(props: unknown): ScatterShapeProps {
  return (props ?? {}) as ScatterShapeProps;
}

function triUp(cx: number, cy: number, s: number) {
  return `${cx},${cy - s} ${cx - s},${cy + s * 0.65} ${cx + s},${cy + s * 0.65}`;
}

function triDown(cx: number, cy: number, s: number) {
  return `${cx},${cy + s} ${cx - s},${cy - s * 0.65} ${cx + s},${cy - s * 0.65}`;
}

function CountBadge({
  cx,
  cy,
  count,
  color,
}: {
  cx: number;
  cy: number;
  count: number;
  color: string;
}) {
  if (count < 2) return null;
  const label = count > 99 ? "99+" : String(count);
  const w = label.length > 1 ? 14 : 11;
  return (
    <g>
      <rect
        x={cx + 3}
        y={cy - 10}
        width={w}
        height={11}
        rx={3}
        fill="#0b1220"
        stroke={color}
        strokeWidth={1}
      />
      <text
        x={cx + 3 + w / 2}
        y={cy - 2}
        textAnchor="middle"
        fill={color}
        fontSize={8}
        fontWeight={700}
        fontFamily="system-ui, sans-serif"
      >
        {label}
      </text>
    </g>
  );
}

/** Green up-triangle; shifts up when a sell is also present on this bar. */
export function TradeBuyShape(props: unknown) {
  const { cx, cy, payload } = asShapeProps(props);
  if (cx == null || cy == null || payload?.buyMark == null) return <g />;
  const buyCount = payload.buyCount ?? 1;
  if (buyCount < 1) return <g />;
  const sellCount = payload.sellCount ?? 0;
  const both = sellCount > 0;
  const y = both ? cy - MARKER_SPLIT_PX : cy;
  return (
    <g>
      <polygon
        points={triUp(cx, y, TRI_SIZE)}
        fill={BUY_COLOR}
        stroke="rgba(15,23,42,0.85)"
        strokeWidth={1}
      />
      <CountBadge cx={cx} cy={y} count={buyCount} color={BUY_COLOR} />
    </g>
  );
}

/** Red down-triangle; shifts down when a buy is also present on this bar. */
export function TradeSellShape(props: unknown) {
  const { cx, cy, payload } = asShapeProps(props);
  if (cx == null || cy == null || payload?.sellMark == null) return <g />;
  const sellCount = payload.sellCount ?? 1;
  if (sellCount < 1) return <g />;
  const buyCount = payload.buyCount ?? 0;
  const both = buyCount > 0;
  const y = both ? cy + MARKER_SPLIT_PX : cy;
  return (
    <g>
      <polygon
        points={triDown(cx, y, TRI_SIZE)}
        fill={SELL_COLOR}
        stroke="rgba(15,23,42,0.85)"
        strokeWidth={1}
      />
      <CountBadge cx={cx} cy={y} count={sellCount} color={SELL_COLOR} />
    </g>
  );
}

/** Inline legend glyph (HTML/SVG). */
export function LegendBuyIcon({ className }: { className?: string }) {
  return (
    <svg width="10" height="10" viewBox="0 0 12 12" className={className} aria-hidden>
      <polygon points="6,1 1,10 11,10" fill={BUY_COLOR} />
    </svg>
  );
}

export function LegendSellIcon({ className }: { className?: string }) {
  return (
    <svg width="10" height="10" viewBox="0 0 12 12" className={className} aria-hidden>
      <polygon points="6,11 1,2 11,2" fill={SELL_COLOR} />
    </svg>
  );
}
