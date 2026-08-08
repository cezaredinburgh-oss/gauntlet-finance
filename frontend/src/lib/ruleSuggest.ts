import type { Transaction } from "../api/types";

export type RuleSuggestion = {
  match_field: "merchant" | "description" | "original_description" | "counterparty_name" | "source_institution";
  match_type: "exact" | "contains" | "starts_with" | "regex";
  match_value: string;
  institution_scope: string | null;
  /** Distinct merchant/label candidates ranked by frequency */
  candidates: Array<{ value: string; count: number }>;
};

export function normalizeLabel(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

/** Stable vendor key for “same merchant” bulk apply. */
export function vendorKey(t: Transaction): string | null {
  if (t.merchant && t.merchant.trim()) {
    return `m:${normalizeLabel(t.merchant).toLowerCase()}`;
  }
  if (t.description && t.description.trim()) {
    const d = normalizeLabel(t.description);
    return `d:${(d.length > 48 ? d.slice(0, 48) : d).toLowerCase()}`;
  }
  return null;
}

export function vendorDisplayName(t: Transaction): string {
  if (t.merchant && t.merchant.trim()) return normalizeLabel(t.merchant);
  if (t.description && t.description.trim()) {
    const d = normalizeLabel(t.description);
    return d.length > 48 ? d.slice(0, 48) : d;
  }
  return "Unknown";
}

/**
 * Other transactions in ``pool`` that share the vendor seed and are not already
 * on ``categoryId`` (unless includeAlreadyCategorized).
 */
export function sameVendorTransactionIds(
  pool: Transaction[],
  seeds: Transaction[],
  categoryId: string,
  opts: { includeAlreadyOnCategory?: boolean } = {},
): string[] {
  const keys = new Set<string>();
  for (const s of seeds) {
    const k = vendorKey(s);
    if (k) keys.add(k);
  }
  if (!keys.size) return [];
  const seedIds = new Set(seeds.map((s) => s.id));
  const out: string[] = [];
  for (const t of pool) {
    if (seedIds.has(t.id)) continue;
    const k = vendorKey(t);
    if (!k || !keys.has(k)) continue;
    if (!opts.includeAlreadyOnCategory && t.category_id === categoryId) continue;
    out.push(t.id);
  }
  return out;
}

function seedFromTx(t: Transaction): { field: RuleSuggestion["match_field"]; value: string } | null {
  if (t.merchant && t.merchant.trim()) {
    return { field: "merchant", value: normalizeLabel(t.merchant) };
  }
  if (t.description && t.description.trim()) {
    const d = normalizeLabel(t.description);
    return { field: "description", value: d.length > 48 ? d.slice(0, 48).trim() : d };
  }
  if (t.original_description && t.original_description.trim()) {
    const d = normalizeLabel(t.original_description);
    return { field: "description", value: d.length > 48 ? d.slice(0, 48).trim() : d };
  }
  return null;
}

/** Build a rule seed from txs that were just categorized. */
export function suggestRuleFromTransactions(txs: Transaction[]): RuleSuggestion | null {
  if (!txs.length) return null;

  const counts = new Map<string, { field: RuleSuggestion["match_field"]; count: number }>();
  for (const t of txs) {
    const seed = seedFromTx(t);
    if (!seed) continue;
    const key = `${seed.field}\0${seed.value.toLowerCase()}`;
    const prev = counts.get(key);
    if (prev) prev.count += 1;
    else counts.set(key, { field: seed.field, count: 1 });
  }
  if (!counts.size) return null;

  const ranked = [...counts.entries()]
    .map(([k, v]) => {
      const value = k.split("\0")[1] ?? "";
      // recover original casing from first matching tx
      let display = value;
      for (const t of txs) {
        const s = seedFromTx(t);
        if (s && s.field === v.field && s.value.toLowerCase() === value) {
          display = s.value;
          break;
        }
      }
      return { field: v.field, value: display, count: v.count };
    })
    .sort((a, b) => b.count - a.count);

  const top = ranked[0];
  const institutions = new Set(
    txs.map((t) => (t.source_institution || "").trim()).filter(Boolean),
  );
  const institution_scope = institutions.size === 1 ? [...institutions][0] : null;

  return {
    match_field: top.field,
    match_type: "contains",
    match_value: top.value,
    institution_scope,
    candidates: ranked.map((r) => ({ value: r.value, count: r.count })),
  };
}

function fieldValue(tx: Transaction, field: string): string {
  switch (field) {
    case "merchant":
      return tx.merchant || "";
    case "description":
      return tx.description || "";
    case "original_description":
      return tx.original_description || "";
    case "source_institution":
      return tx.source_institution || "";
    default:
      return "";
  }
}

/** How many txs would match (simple client preview; ignores regex). */
export function countRuleMatches(
  txs: Transaction[],
  opts: {
    match_field: string;
    match_type: string;
    match_value: string;
    institution_scope?: string | null;
    onlyWithoutOverride?: boolean;
    onlyUncategorized?: boolean;
  },
): number {
  const needle = opts.match_value.trim().toLowerCase();
  if (!needle) return 0;
  let n = 0;
  for (const t of txs) {
    if (opts.onlyWithoutOverride && t.category_override) continue;
    if (opts.onlyUncategorized && t.category_id) continue;
    if (
      opts.institution_scope &&
      (t.source_institution || "").toLowerCase() !== opts.institution_scope.toLowerCase()
    ) {
      continue;
    }
    const hay = fieldValue(t, opts.match_field).toLowerCase();
    if (!hay) continue;
    let ok = false;
    if (opts.match_type === "exact") ok = hay === needle;
    else if (opts.match_type === "starts_with") ok = hay.startsWith(needle);
    else if (opts.match_type === "contains") ok = hay.includes(needle);
    else if (opts.match_type === "regex") {
      try {
        ok = new RegExp(opts.match_value, "i").test(fieldValue(t, opts.match_field));
      } catch {
        ok = false;
      }
    }
    if (ok) n += 1;
  }
  return n;
}
