/**
 * Published xAI list rates (USD / 1M tokens). Estimates only — not an invoice.
 * grok-4.3: $1.25 / $2.50 · grok-4.5 and grok-4.6: $2 / $6
 */
export type ModelRates = {
  inputPerM: number;
  outputPerM: number;
};

const RATES: Record<string, ModelRates> = {
  "grok-4.3": { inputPerM: 1.25, outputPerM: 2.5 },
  "grok-4.5": { inputPerM: 2, outputPerM: 6 },
  "grok-4.6": { inputPerM: 2, outputPerM: 6 },
};

const DEFAULT_RATES = RATES["grok-4.3"];

export function ratesForModel(model: string | null | undefined): ModelRates {
  const key = (model || "").trim().toLowerCase();
  if (key in RATES) return RATES[key];
  if (key.includes("4.5") || key.includes("4.6")) return RATES["grok-4.5"];
  return DEFAULT_RATES;
}

/** When only a total is known (daily quota), assume 80% input / 20% output. */
export function estimateUsd(opts: {
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
  model?: string | null;
}): number {
  const rates = ratesForModel(opts.model);
  let prompt = Math.max(0, opts.promptTokens ?? 0);
  let completion = Math.max(0, opts.completionTokens ?? 0);
  const total = Math.max(0, opts.totalTokens ?? 0);
  if (prompt + completion <= 0 && total > 0) {
    prompt = Math.round(total * 0.8);
    completion = total - prompt;
  }
  return (prompt / 1_000_000) * rates.inputPerM + (completion / 1_000_000) * rates.outputPerM;
}

/** Estimate leftover-Grok $ to hit coverage targets. Memory/local hits are free. */
export function estimateGrokPlusLadder(opts: {
  categorized: number;
  uncategorized: number;
  leftoverVendors: number;
  usdPerLeftoverBatch: number;
  vendorsPerBatch?: number;
}): { pct: number; needTx: number; estUsd: number }[] {
  const total = Math.max(0, opts.categorized + opts.uncategorized);
  const perBatch = Math.max(1, opts.vendorsPerBatch ?? 12);
  const rate = Math.max(0, opts.usdPerLeftoverBatch);
  const avgTx =
    opts.leftoverVendors > 0 ? opts.uncategorized / opts.leftoverVendors : 1;
  return [50, 75, 90].map((pct) => {
    const target = Math.ceil((pct / 100) * total);
    const needTx = Math.max(0, target - opts.categorized);
    const needVendors = avgTx > 0 ? needTx / avgTx : 0;
    const batches = Math.ceil(needVendors / perBatch);
    return { pct, needTx, estUsd: batches * rate };
  });
}

export function formatUsdEstimate(usd: number): string {
  if (!Number.isFinite(usd) || usd <= 0) return "$0.00";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}
