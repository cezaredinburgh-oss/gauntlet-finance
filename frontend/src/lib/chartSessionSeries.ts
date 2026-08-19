import type { ChartSessionTag } from "../api/types";

export type SessionPoint = {
  date: string;
  value: string | number;
  session?: ChartSessionTag | null;
};

export type SplitSessionRow = {
  date: string;
  value: number;
  rthValue: number | null;
  extValue: number | null;
  session?: ChartSessionTag | null;
};

const EXT_SESSIONS = new Set<ChartSessionTag | null | undefined>([
  "pre",
  "ah",
  "prior_close",
]);

function numValue(v: string | number): number {
  return typeof v === "number" ? v : Number(v);
}

/** RTH Area vs dashed pre/AH/seed Line. Untagged / crypto tapes stay a solid Area. */
export function splitSessionSeries(points: readonly SessionPoint[]): SplitSessionRow[] {
  const rows = points.map((p) => ({
    date: p.date,
    value: numValue(p.value),
    session: p.session ?? null,
  }));
  const tagged = rows.some(
    (p) =>
      p.session === "pre" ||
      p.session === "rth" ||
      p.session === "ah" ||
      p.session === "prior_close",
  );
  if (!tagged) {
    return rows.map((p) => ({
      date: p.date,
      value: p.value,
      rthValue: Number.isFinite(p.value) ? p.value : null,
      extValue: null,
      session: p.session,
    }));
  }
  const firstRth = rows.findIndex((p) => p.session === "rth");
  let lastRth = -1;
  for (let i = rows.length - 1; i >= 0; i--) {
    if (rows[i].session === "rth") {
      lastRth = i;
      break;
    }
  }
  return rows.map((p, i) => {
    const isRth = p.session === "rth";
    const joinCopy = isRth && (i === firstRth || i === lastRth);
    const isExt = EXT_SESSIONS.has(p.session) || joinCopy;
    return {
      date: p.date,
      value: p.value,
      rthValue: isRth ? p.value : null,
      extValue: isExt ? p.value : null,
      session: p.session,
    };
  });
}

export function rthValuesOf(rows: readonly SplitSessionRow[]): number[] {
  return rows
    .map((r) => r.rthValue)
    .filter((v): v is number => v != null && Number.isFinite(v));
}
