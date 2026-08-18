export const COST_MIN_SPAN_FRACTION = 0.35;
export const COST_FLAT_REL_EPS = 0.005;
export const COST_DOMAIN_PAD = 0.04;

export function shouldShowCostBasis(
  cost: number,
  values: readonly number[],
  minSpanFraction: number = COST_MIN_SPAN_FRACTION,
): boolean {
  const finite = values.filter((v) => Number.isFinite(v));
  if (!Number.isFinite(cost) || finite.length === 0) return false;
  const pMin = Math.min(...finite);
  const pMax = Math.max(...finite);
  const pRange = pMax - pMin;
  if (pRange === 0) {
    const scale = Math.max(Math.abs(pMin), 1e-9);
    return Math.abs(cost - pMin) / scale < COST_FLAT_REL_EPS;
  }
  if (cost >= pMin && cost <= pMax) return true;
  const dRange = Math.max(pMax, cost) - Math.min(pMin, cost);
  return pRange / dRange >= minSpanFraction;
}

export function chartYDomain(
  values: readonly number[],
  opts: { cost?: number; showCost: boolean; pad?: number } = { showCost: false },
): [number, number] {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return [0, 1];
  let lo = Math.min(...finite);
  let hi = Math.max(...finite);
  if (opts.showCost && opts.cost != null && Number.isFinite(opts.cost)) {
    lo = Math.min(lo, opts.cost);
    hi = Math.max(hi, opts.cost);
  }
  const pad = opts.pad ?? COST_DOMAIN_PAD;
  const span = hi - lo;
  const bump = span === 0 ? Math.max(Math.abs(lo) * pad, 1e-9) : span * pad;
  return [lo - bump, hi + bump];
}
