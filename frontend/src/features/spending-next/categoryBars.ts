/** Ranked spending bars: top 25 + named rollup. Number() of API decimals is display-only. */

export const CATEGORY_TOP_N = 25;

export const NECESSITY_COLORS: Record<string, string> = {
  Fixed: "#38bdf8",
  VariableNecessity: "#a78bfa",
  Discretionary: "#fbbf24",
};

export const NECESSITY_LABEL: Record<string, string> = {
  Fixed: "Fixed",
  VariableNecessity: "Variable",
  Discretionary: "Discretionary",
};

export type CategoryBarInput = {
  id: string;
  name: string;
  amount_usd: string | number;
  life_domain: string;
  necessity: string;
  pct_of_spend: number;
};

export type CategoryBar = {
  id: string;
  name: string;
  value: number;
  life_domain: string;
  necessity: string;
  pct: number;
  rollupIds?: string[];
  rollupNames?: string[];
};

function apiNumber(value: string | number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** ≤25 rows pass through; 26+ keeps top 25 and rolls the tail into `other_rollup`. */
export function buildCategoryBars(rows: CategoryBarInput[]): CategoryBar[] {
  const mapped: CategoryBar[] = rows.map((e) => ({
    id: e.id,
    name: e.name,
    value: apiNumber(e.amount_usd),
    life_domain: e.life_domain,
    necessity: e.necessity,
    pct: e.pct_of_spend,
  }));
  if (mapped.length <= CATEGORY_TOP_N) return mapped;

  const top = mapped.slice(0, CATEGORY_TOP_N);
  const rest = mapped.slice(CATEGORY_TOP_N);
  return [
    ...top,
    {
      id: "other_rollup",
      name: `Smaller categories (${rest.length})`,
      value: rest.reduce((s, r) => s + r.value, 0),
      life_domain: "Mixed",
      necessity: "Discretionary",
      pct: rest.reduce((s, r) => s + r.pct, 0),
      rollupIds: rest.map((r) => r.id),
      rollupNames: rest.map((r) => r.name),
    },
  ];
}

export function categoryChartHeight(n: number): number {
  return Math.max(280, n * 32 + 40);
}

/** Axis labels only — never truncate amounts. */
export function truncateCategoryName(name: string, max = 18): string {
  if (name.length <= max) return name;
  return `${name.slice(0, Math.max(1, max - 1))}…`;
}
