/**
 * Self-test for Grok+ batch merge (append, no wipe, no resurrect).
 * Run: npx --yes tsx src/lib/grokPlus.selftest.ts  (from frontend/)
 */
import { mergePlusBatch, pickLatestMatch } from "./grokPlus";
import type { AiCategorySuggestion, Category } from "../api/types";
import type { VendorBucket } from "./ruleSuggest";

function cat(id: string, name: string): Category {
  return {
    id,
    name,
    parent_id: null,
    necessity: "need",
    life_domain: "Living",
    is_income: false,
    is_transfer: false,
    sort_order: 1,
  };
}

const cats: Category[] = [cat("cat-groc", "Groceries"), cat("cat-fuel", "Fuel (car)")];

function sug(
  partial: Partial<AiCategorySuggestion> & { merchant_key: string; label: string },
): AiCategorySuggestion {
  return {
    category_id: "",
    category_name: "",
    confidence: 0.8,
    reason: "test",
    transaction_ids: ["t1"],
    sample_count: 1,
    ...partial,
  };
}

const lidl: VendorBucket = {
  key: "m:lidl",
  label: "Lidl",
  count: 3,
  ids: ["a", "b", "c"],
  suggestedCategoryId: "cat-groc",
  suggestedCategoryName: "Groceries",
};

const first = mergePlusBatch({
  prev: [lidl],
  exclude: ["m:lidl"],
  consumed: [],
  suggestions: [
    sug({
      merchant_key: "m:mol",
      label: "MOL",
      category_id: "cat-fuel",
      category_name: "Fuel (car)",
    }),
  ],
  vendorsSent: [{ merchant_key: "m:mol" }],
  cats,
});
if (first.buckets.length !== 2) throw new Error("should append, not wipe");
if (first.buckets[0].key !== "m:lidl") throw new Error("keep prior first");
if (first.added.length !== 1 || first.added[0].label !== "MOL") {
  throw new Error("added MOL");
}
if (!first.exclude.includes("m:mol") || !first.exclude.includes("m:lidl")) {
  throw new Error("exclude grows");
}

const resurrect = mergePlusBatch({
  prev: first.buckets,
  exclude: first.exclude,
  consumed: ["m:lidl"],
  suggestions: [
    sug({
      merchant_key: "m:lidl",
      label: "Lidl",
      category_id: "cat-groc",
      category_name: "Groceries",
    }),
  ],
  vendorsSent: [{ merchant_key: "m:lidl" }],
  cats,
});
if (resurrect.added.length !== 0) throw new Error("must not resurrect consumed");
if (resurrect.buckets.filter((b) => b.key === "m:lidl").length !== 1) {
  throw new Error("existing lidl stays once");
}

const latest = pickLatestMatch(first.added);
if (!latest || latest.label !== "MOL" || latest.categoryName !== "Fuel (car)") {
  throw new Error(`latest match ${JSON.stringify(latest)}`);
}

console.log("grokPlus.selftest: ok");
