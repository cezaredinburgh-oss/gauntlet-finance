import type { AiCategorySuggestion, Category } from "../api/types";
import type { VendorBucket } from "./ruleSuggest";

export const GROK_PLUS_BATCH = 12;
export const GROK_PLUS_SESSION_CAP = 80;

export type GrokPlusPhase = "idle" | "running" | "paused" | "caught_up" | "error";

export function grokPlusStatusLabel(phase: string, bucketCount: number): string {
  if (phase === "running") return "Working — matching leftovers";
  if (phase === "paused") return bucketCount ? "Paused — ready for review" : "Paused";
  if (phase === "caught_up") return bucketCount ? "Ready for review" : "Caught up";
  if (phase === "error") return "Stopped — see message";
  if (bucketCount) return "Ready for review";
  return "Grok+ idle";
}

export function grokPlusMinimizedLabel(phase: string, bucketCount: number): string {
  if (phase === "running") return "Working";
  if (phase === "paused") return bucketCount ? "Paused — ready for review" : "Paused";
  if (phase === "caught_up") return bucketCount ? "Ready for review" : "Caught up";
  if (phase === "error") return "Stopped";
  if (bucketCount) return "Ready for review";
  return "Grok+";
}

/** running → paused on restore. */
export function restorePhase(raw: unknown, bucketCount: number): GrokPlusPhase {
  if (raw === "error") return "error";
  if (raw === "caught_up") return "caught_up";
  if (raw === "paused" || raw === "running") return "paused";
  if (bucketCount > 0) return "paused";
  return "idle";
}

/** Session chrome (status + Play) stays up after restore even with 0 buckets. */
export function grokPlusSessionStarted(phase: string, bucketCount: number): boolean {
  return (
    bucketCount > 0 ||
    phase === "paused" ||
    phase === "caught_up" ||
    phase === "error"
  );
}

export function mapGrokSuggestions(
  suggestions: AiCategorySuggestion[],
  catsSorted: Category[],
): VendorBucket[] {
  return suggestions.map((s) => {
    const want = (s.category_id || "").trim().toLowerCase();
    const byId = want
      ? catsSorted.find((c) => c.id.toLowerCase() === want)
      : undefined;
    const byName = s.category_name
      ? catsSorted.find(
          (c) => c.name.toLowerCase() === s.category_name.trim().toLowerCase(),
        )
      : undefined;
    const resolved = byId || byName;
    return {
      key: s.merchant_key,
      label: s.label,
      count: s.sample_count || s.transaction_ids.length,
      ids: s.transaction_ids,
      suggestedCategoryId: resolved?.id || "",
      suggestedCategoryName: resolved?.name || s.category_name,
      reason: s.reason
        ? `${s.reason}${resolved?.name || s.category_name ? ` → ${resolved?.name || s.category_name}` : ""}`
        : resolved?.name || s.category_name || undefined,
      confidence: s.confidence,
    };
  });
}

export type PlusBatchInput = {
  prev: VendorBucket[];
  exclude: string[];
  consumed: string[];
  suggestions: AiCategorySuggestion[];
  vendorsSent: Array<{ merchant_key: string }>;
  cats: Category[];
};

export type PlusBatchResult = {
  buckets: VendorBucket[];
  exclude: string[];
  added: VendorBucket[];
};

/** Append a plus response. Never resurrect consumed keys. Never drop prior guesses. */
export function mergePlusBatch(input: PlusBatchInput): PlusBatchResult {
  const exclude = new Set(input.exclude.filter(Boolean));
  const consumed = new Set(input.consumed.filter(Boolean));
  const have = new Set(input.prev.map((b) => b.key));
  for (const v of input.vendorsSent) {
    if (v.merchant_key) exclude.add(v.merchant_key);
  }
  for (const s of input.suggestions) {
    if (s.merchant_key) exclude.add(s.merchant_key);
  }
  const added = mapGrokSuggestions(input.suggestions, input.cats).filter(
    (b) => Boolean(b.key) && !consumed.has(b.key) && !have.has(b.key),
  );
  return {
    buckets: [...input.prev, ...added],
    exclude: [...exclude],
    added,
  };
}

export function pickLatestMatch(
  added: VendorBucket[],
): { label: string; categoryName: string } | null {
  if (!added.length) return null;
  const named = added.find((b) => (b.suggestedCategoryName || "").trim());
  const row = named || added[0];
  return {
    label: row.label,
    categoryName: (row.suggestedCategoryName || "").trim() || "needs review",
  };
}
