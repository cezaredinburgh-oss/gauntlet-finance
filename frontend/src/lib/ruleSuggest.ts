import type { Category, Transaction } from "../api/types";

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

/**
 * Residual / still-to-categorize: null, missing cat, Other, Uncategorized,
 * or life_domain Other. Real assigned categories are not residual.
 */
export function isResidualCategory(
  t: Transaction,
  catMap: Map<string, Category>,
): boolean {
  if (!t.category_id) return true;
  const c = catMap.get(t.category_id);
  if (!c) return true;
  const name = (c.name || "").toLowerCase();
  if (name === "other" || name === "uncategorized") return true;
  if ((c.life_domain || "").toLowerCase() === "other") return true;
  return false;
}

/**
 * Similar txs for guided review: same vendor key, optionally same amount sign.
 * Excludes seed ids. Does not require a target category.
 *
 * residualOnly (default true with catMap): omit already-categorized rows so
 * the review list is work remaining, not false positives already done.
 * Results sorted A–Z by vendor display name for fast untick of outliers.
 */
export function findSimilarTransactions(
  pool: Transaction[],
  seeds: Transaction[],
  opts: {
    sameAmountSign?: boolean;
    limit?: number;
    residualOnly?: boolean;
    catMap?: Map<string, Category>;
    sortAlpha?: boolean;
  } = {},
): Transaction[] {
  const keys = new Set<string>();
  const seedIds = new Set(seeds.map((s) => s.id));
  let seedSign: "in" | "out" | "zero" | "mixed" | null = null;
  for (const s of seeds) {
    const k = vendorKey(s);
    if (k) keys.add(k);
    const n = Number(
      s.amount_usd != null && s.amount_usd !== "" ? s.amount_usd : s.amount,
    );
    const sign: "in" | "out" | "zero" =
      !Number.isFinite(n) || n === 0 ? "zero" : n > 0 ? "in" : "out";
    if (seedSign === null) seedSign = sign;
    else if (seedSign !== sign && sign !== "zero" && seedSign !== "zero") {
      seedSign = "mixed";
    }
  }
  if (!keys.size) return [];

  const residualOnly = opts.residualOnly !== false && opts.catMap != null;
  const out: Transaction[] = [];
  for (const t of pool) {
    if (seedIds.has(t.id)) continue;
    const k = vendorKey(t);
    if (!k || !keys.has(k)) continue;
    if (residualOnly && opts.catMap && !isResidualCategory(t, opts.catMap)) {
      continue;
    }
    if (opts.sameAmountSign && seedSign && seedSign !== "mixed" && seedSign !== "zero") {
      const n = Number(
        t.amount_usd != null && t.amount_usd !== "" ? t.amount_usd : t.amount,
      );
      const sign: "in" | "out" | "zero" =
        !Number.isFinite(n) || n === 0 ? "zero" : n > 0 ? "in" : "out";
      if (sign !== "zero" && sign !== seedSign) continue;
    }
    out.push(t);
    if (opts.limit != null && out.length >= opts.limit) break;
  }
  if (opts.sortAlpha !== false) {
    out.sort((a, b) =>
      vendorDisplayName(a).localeCompare(vendorDisplayName(b), undefined, {
        sensitivity: "base",
      }),
    );
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

export type VendorBucket = {
  key: string;
  label: string;
  count: number;
  ids: string[];
  suggestedCategoryId?: string;
  suggestedCategoryName?: string;
  reason?: string;
  confidence?: number;
};

/** Collapse txs to one row per vendor, largest count first. */
export function groupTransactionsByVendor(txs: Transaction[]): VendorBucket[] {
  const buckets = new Map<string, { label: string; ids: string[] }>();
  for (const t of txs) {
    const key = vendorKey(t) ?? "none";
    const label = vendorKey(t) ? vendorDisplayName(t) : "(no label)";
    const prev = buckets.get(key);
    if (prev) prev.ids.push(t.id);
    else buckets.set(key, { label, ids: [t.id] });
  }
  return [...buckets.entries()]
    .map(([key, v]) => ({
      key,
      label: v.label,
      count: v.ids.length,
      ids: v.ids,
    }))
    .sort(
      (a, b) =>
        b.count - a.count ||
        a.label.localeCompare(b.label, undefined, { sensitivity: "base" }),
    );
}

const NON_VENDOR_LABEL =
  /\b(to pocket|from pocket|purchase vault|from vault|to vault|exchanged to|exchange to|exchanged from|incoming payment|outgoing payment|card payment|top-?up|topup|top up|transfer to|transfer from|between own|own account|sent to|sent from|me to me)\b/i;

export function isSearchableVendorBucket(bucket: VendorBucket): boolean {
  const blob = `${bucket.label} ${bucket.key}`;
  if (NON_VENDOR_LABEL.test(blob)) return false;
  if (bucket.key.startsWith("d:")) {
    const low = (bucket.label || "").trim().toLowerCase();
    if (/^(incoming|outgoing|payment|card payment)\b/.test(low)) return false;
  }
  return true;
}

export type CategoryVendorGroup = {
  categoryId: string;
  categoryName: string;
  vendors: VendorBucket[];
  txCount: number;
};

/** Overlay per-vendor category edits so the drill-down regroups immediately. */
export function applyVendorCategoryOverrides(
  buckets: VendorBucket[],
  remaps: Record<string, string>,
  cats: Category[],
): VendorBucket[] {
  if (!Object.keys(remaps).length) return buckets;
  return buckets.map((b) => {
    if (!(b.key in remaps)) return b;
    const id = remaps[b.key];
    if (!id) {
      return { ...b, suggestedCategoryId: "", suggestedCategoryName: "" };
    }
    const cat = cats.find((c) => c.id === id);
    return {
      ...b,
      suggestedCategoryId: id,
      suggestedCategoryName: cat?.name || b.suggestedCategoryName || "",
    };
  });
}

export function groupVendorsByCategory(buckets: VendorBucket[]): {
  groups: CategoryVendorGroup[];
  unassigned: VendorBucket[];
} {
  const unassigned: VendorBucket[] = [];
  const byCat = new Map<string, VendorBucket[]>();
  for (const b of buckets) {
    if (!b.suggestedCategoryId) {
      unassigned.push(b);
      continue;
    }
    const arr = byCat.get(b.suggestedCategoryId) || [];
    arr.push(b);
    byCat.set(b.suggestedCategoryId, arr);
  }
  const groups = [...byCat.entries()]
    .map(([categoryId, vendors]) => ({
      categoryId,
      categoryName: vendors[0]?.suggestedCategoryName || "Category",
      vendors,
      txCount: vendors.reduce((n, v) => n + v.count, 0),
    }))
    .sort(
      (a, b) =>
        b.txCount - a.txCount ||
        a.categoryName.localeCompare(b.categoryName, undefined, {
          sensitivity: "base",
        }),
    );
  return { groups, unassigned };
}

/** Comma-separated vendor names that fit in ``maxChars``, then “+N more”. */
export function formatVendorPreview(names: string[], maxChars = 72): string {
  const out: string[] = [];
  let used = 0;
  for (let i = 0; i < names.length; i++) {
    const name = names[i];
    const piece = out.length ? `, ${name}` : name;
    const rest = names.length - i;
    const more = rest > 1 ? `, +${rest} more` : "";
    if (out.length > 0 && used + piece.length + (rest > 1 ? more.length : 0) > maxChars) {
      out.push(`+${rest} more`);
      break;
    }
    out.push(name);
    used += piece.length;
  }
  return out.join(", ");
}

export function selectSearchableVendorBuckets(
  buckets: VendorBucket[],
  limit = 10,
): VendorBucket[] {
  return buckets
    .filter(isSearchableVendorBucket)
    .sort((a, b) => {
      const am = a.key.startsWith("m:") ? 0 : 1;
      const bm = b.key.startsWith("m:") ? 0 : 1;
      return (
        am - bm ||
        b.count - a.count ||
        a.label.localeCompare(b.label, undefined, { sensitivity: "base" })
      );
    })
    .slice(0, Math.max(0, limit));
}

export type LedgerCategoryCounts = {
  categorized: number;
  uncategorized: number;
  total: number;
  pct: number;
};

/** Count residual vs real-category rows. Internal transfers are skipped. */
export function ledgerCategoryCounts(
  txs: Transaction[],
  catMap: Map<string, Category>,
): LedgerCategoryCounts {
  let categorized = 0;
  let uncategorized = 0;
  for (const t of txs) {
    if (t.is_internal_transfer) continue;
    if (isResidualCategory(t, catMap)) uncategorized += 1;
    else categorized += 1;
  }
  const total = categorized + uncategorized;
  const pct = total > 0 ? (categorized / total) * 100 : 0;
  return { categorized, uncategorized, total, pct };
}
