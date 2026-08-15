/**
 * Self-test for Grok USD estimates.
 * Run: npx --yes tsx src/lib/aiCost.selftest.ts  (from frontend/)
 */
import { estimateUsd, formatUsdEstimate, ratesForModel } from "./aiCost";

const r43 = ratesForModel("grok-4.3");
if (r43.inputPerM !== 1.25 || r43.outputPerM !== 2.5) {
  throw new Error("grok-4.3 rates");
}
const r45 = ratesForModel("grok-4.5");
if (r45.inputPerM !== 2 || r45.outputPerM !== 6) {
  throw new Error("grok-4.5 rates");
}
if (ratesForModel("unknown-model").inputPerM !== 1.25) {
  throw new Error("unknown model should fall back to 4.3");
}

const oneMIn = estimateUsd({ promptTokens: 1_000_000, completionTokens: 0, model: "grok-4.3" });
if (Math.abs(oneMIn - 1.25) > 1e-9) throw new Error(`1M input 4.3 => ${oneMIn}`);

const oneMOut = estimateUsd({ promptTokens: 0, completionTokens: 1_000_000, model: "grok-4.5" });
if (Math.abs(oneMOut - 6) > 1e-9) throw new Error(`1M output 4.5 => ${oneMOut}`);

const blended = estimateUsd({ totalTokens: 1_000_000, model: "grok-4.3" });
const expectBlend = 0.8 * 1.25 + 0.2 * 2.5;
if (Math.abs(blended - expectBlend) > 1e-9) throw new Error(`blend => ${blended}`);

if (formatUsdEstimate(0) !== "$0.00") throw new Error("zero format");
if (formatUsdEstimate(0.0042) !== "$0.0042") throw new Error("tiny format");
if (formatUsdEstimate(1.2) !== "$1.20") throw new Error("dollar format");

console.log("aiCost.selftest: ok");
