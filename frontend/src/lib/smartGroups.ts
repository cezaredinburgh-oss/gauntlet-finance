/**
 * Smart triage groups for Categorize → Groups mode.
 * Pure helpers over a loaded transaction pool (no API).
 */

import type { Category, Transaction } from "../api/types";
import { vendorKey } from "./ruleSuggest";

export type SmartGroupId =
  | "large_amounts"
  | "near_identical"
  | "suspected_transfers"
  | "uncategorized_income"
  | "stuck_other"
  | "recurring"
  | "top_merchants"
  | "fees_atm";

export type SmartGroupCluster = {
  key: string;
  label: string;
  transactionIds: string[];
  sampleAmount?: number;
  hint?: string;
};

export type SmartGroup = {
  id: SmartGroupId;
  title: string;
  description: string;
  /** Flat tx ids (for simple lists) */
  transactionIds: string[];
  /** Optional cluster breakdown */
  clusters: SmartGroupCluster[];
};

function absAmount(t: Transaction): number {
  const raw =
    t.amount_usd != null && t.amount_usd !== "" ? t.amount_usd : t.amount;
  const n = Number(raw);
  return Number.isFinite(n) ? Math.abs(n) : 0;
}

/** Newest booking_date first (ISO date strings sort lexicographically). */
function sortNewestFirst(ids: string[], byId: Map<string, Transaction>): string[] {
  return ids.slice().sort((a, b) => {
    const da = byId.get(a)?.booking_date || "";
    const db = byId.get(b)?.booking_date || "";
    if (da !== db) return db.localeCompare(da);
    return a.localeCompare(b);
  });
}

function clusterLatestDate(ids: string[], byId: Map<string, Transaction>): string {
  let best = "";
  for (const id of ids) {
    const d = byId.get(id)?.booking_date || "";
    if (d > best) best = d;
  }
  return best;
}

function signedAmount(t: Transaction): number {
  const raw =
    t.amount_usd != null && t.amount_usd !== "" ? t.amount_usd : t.amount;
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

function isExpense(t: Transaction): boolean {
  return signedAmount(t) < 0;
}

function isIncome(t: Transaction): boolean {
  return signedAmount(t) > 0;
}

function isBlankOrOther(
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

const TRANSFER_HINT =
  /\b(transfer|xfer|p2p|own account|me to me|internal| sto |t\/t|příchozí|odchozí|prevod|převod)\b/i;
const FEE_ATM_HINT =
  /\b(fee|charge|atm|cash withdraw|výběr|poplatek|commission|fx fee)\b/i;

/**
 * Build smart groups from a transaction pool.
 */
export function buildSmartGroups(
  pool: Transaction[],
  categories: Category[],
  opts: {
    largeTopN?: number;
    largeMinAbs?: number;
    nearIdenticalMin?: number;
    recurringMinMonths?: number;
  } = {},
): SmartGroup[] {
  const largeTopN = opts.largeTopN ?? 25;
  const largeMinAbs = opts.largeMinAbs ?? 150;
  const nearIdenticalMin = opts.nearIdenticalMin ?? 2;
  const catMap = new Map(categories.map((c) => [c.id, c]));
  const byId = new Map(pool.map((t) => [t.id, t]));

  const expenses = pool.filter((t) => isExpense(t) && !t.is_internal_transfer);
  // Prefer recent large spends: among top abs, sort newest first
  const byAbs = expenses
    .slice()
    .sort((a, b) => {
      const da = absAmount(a) - absAmount(b);
      if (Math.abs(da) > 0.01) return absAmount(b) - absAmount(a);
      return (b.booking_date || "").localeCompare(a.booking_date || "");
    });
  const largeCut = byAbs.filter((t) => absAmount(t) >= largeMinAbs);
  const largeIds = sortNewestFirst(
    (largeCut.length >= 5 ? largeCut : byAbs).slice(0, largeTopN).map((t) => t.id),
    byId,
  );

  // Near-identical: same vendor key + similar amount (2% or exact)
  const nearBuckets = new Map<string, Transaction[]>();
  for (const t of pool) {
    if (t.is_internal_transfer) continue;
    const vk = vendorKey(t);
    if (!vk) continue;
    const amt = signedAmount(t);
    const band = Math.round(amt * 100) / 100; // exact cents first
    const key = `${vk}|${band}`;
    const arr = nearBuckets.get(key) || [];
    arr.push(t);
    nearBuckets.set(key, arr);
  }
  const nearClusters: SmartGroupCluster[] = [];
  for (const [key, txs] of nearBuckets) {
    if (txs.length < nearIdenticalMin) continue;
    const label = txs[0].merchant || txs[0].description || key;
    nearClusters.push({
      key,
      label,
      transactionIds: txs.map((t) => t.id),
      sampleAmount: signedAmount(txs[0]),
      hint: `${txs.length}× same amount`,
    });
  }
  for (const c of nearClusters) {
    c.transactionIds = sortNewestFirst(c.transactionIds, byId);
  }
  nearClusters.sort((a, b) => {
    const ld = clusterLatestDate(b.transactionIds, byId).localeCompare(
      clusterLatestDate(a.transactionIds, byId),
    );
    if (ld !== 0) return ld;
    return b.transactionIds.length - a.transactionIds.length;
  });

  // Suspected internal transfers (not already flagged)
  const suspected = pool.filter((t) => {
    if (t.is_internal_transfer) return false;
    const cat = t.category_id ? catMap.get(t.category_id) : undefined;
    if (cat?.is_transfer) return false;
    const text = `${t.merchant || ""} ${t.description || ""} ${t.original_description || ""}`;
    return TRANSFER_HINT.test(text);
  });

  // Uncategorized income
  const uncatIncome = pool.filter(
    (t) => isIncome(t) && !t.is_internal_transfer && isBlankOrOther(t, catMap),
  );

  // Stuck in Other
  const stuckOther = pool.filter((t) => {
    if (!t.category_id) return false;
    const c = catMap.get(t.category_id);
    if (!c) return false;
    const name = (c.name || "").toLowerCase();
    return (
      name === "other" ||
      name === "uncategorized" ||
      (c.life_domain || "").toLowerCase() === "other"
    );
  });

  // Recurring: same vendor, similar abs amount, ≥2 distinct months
  const byVendor = new Map<string, Transaction[]>();
  for (const t of pool) {
    if (t.is_internal_transfer) continue;
    const vk = vendorKey(t);
    if (!vk) continue;
    const arr = byVendor.get(vk) || [];
    arr.push(t);
    byVendor.set(vk, arr);
  }
  const recurringClusters: SmartGroupCluster[] = [];
  for (const [vk, txs] of byVendor) {
    if (txs.length < 2) continue;
    const months = new Set(
      txs.map((t) => (t.booking_date || "").slice(0, 7)).filter(Boolean),
    );
    if (months.size < 2) continue;
    const amounts = txs.map(absAmount).filter((a) => a > 0);
    if (!amounts.length) continue;
    const median = amounts.slice().sort((a, b) => a - b)[Math.floor(amounts.length / 2)];
    const similar = txs.filter((t) => {
      const a = absAmount(t);
      if (median === 0) return false;
      return Math.abs(a - median) / median <= 0.08;
    });
    if (similar.length < 2 || new Set(similar.map((t) => (t.booking_date || "").slice(0, 7))).size < 2) {
      continue;
    }
    recurringClusters.push({
      key: vk,
      label: similar[0].merchant || similar[0].description || vk,
      transactionIds: similar.map((t) => t.id),
      sampleAmount: -median,
      hint: `${months.size} months · ~same amount`,
    });
  }

  // Top merchants by count (blank/other preferred in sort)
  const merchantCounts = new Map<string, { label: string; ids: string[]; blank: number }>();
  for (const t of pool) {
    if (t.is_internal_transfer) continue;
    const vk = vendorKey(t);
    if (!vk) continue;
    const cur = merchantCounts.get(vk) || {
      label: t.merchant || t.description || vk,
      ids: [],
      blank: 0,
    };
    cur.ids.push(t.id);
    if (isBlankOrOther(t, catMap)) cur.blank += 1;
    merchantCounts.set(vk, cur);
  }
  const topMerchants: SmartGroupCluster[] = [...merchantCounts.entries()]
    .map(([key, v]) => ({
      key,
      label: v.label,
      transactionIds: v.ids,
      hint: `${v.ids.length} txs · ${v.blank} need category`,
    }))
    .filter((c) => c.transactionIds.length >= 3)
    .sort((a, b) => b.transactionIds.length - a.transactionIds.length)
    .slice(0, 15);

  // Fees / ATM
  const feesAtm = pool.filter((t) => {
    const text = `${t.merchant || ""} ${t.description || ""} ${t.original_description || ""}`;
    return FEE_ATM_HINT.test(text);
  });

  for (const c of recurringClusters) {
    c.transactionIds = sortNewestFirst(c.transactionIds, byId);
  }
  recurringClusters.sort((a, b) => {
    const ld = clusterLatestDate(b.transactionIds, byId).localeCompare(
      clusterLatestDate(a.transactionIds, byId),
    );
    if (ld !== 0) return ld;
    return b.transactionIds.length - a.transactionIds.length;
  });

  for (const c of topMerchants) {
    c.transactionIds = sortNewestFirst(c.transactionIds, byId);
  }

  const groups: SmartGroup[] = [
    {
      id: "large_amounts",
      title: "Large amounts",
      description: "Highest-value expenses in the current scope — categorize these first for coverage impact.",
      transactionIds: largeIds,
      clusters: [],
    },
    {
      id: "near_identical",
      title: "Near-identical",
      description: "Same merchant and same amount — usually safe to group-assign one category.",
      transactionIds: nearClusters.flatMap((c) => c.transactionIds),
      clusters: nearClusters.slice(0, 40),
    },
    {
      id: "suspected_transfers",
      title: "Suspected internal transfers",
      description: "Look like account-to-account moves but are not flagged internal yet.",
      transactionIds: sortNewestFirst(
        suspected.map((t) => t.id),
        byId,
      ),
      clusters: [],
    },
    {
      id: "uncategorized_income",
      title: "Uncategorized income",
      description: "Money in without a clear category (salary, refunds, transfers in).",
      transactionIds: sortNewestFirst(
        uncatIncome.map((t) => t.id),
        byId,
      ),
      clusters: [],
    },
    {
      id: "stuck_other",
      title: "Stuck in Other",
      description: "Tagged Other / Uncategorized — they still hurt spending coverage.",
      transactionIds: sortNewestFirst(
        stuckOther.map((t) => t.id),
        byId,
      ),
      clusters: [],
    },
    {
      id: "recurring",
      title: "Recurring / subscription-like",
      description: "Same merchant across months with a stable amount.",
      transactionIds: recurringClusters.flatMap((c) => c.transactionIds),
      clusters: recurringClusters.slice(0, 30),
    },
    {
      id: "top_merchants",
      title: "Top merchants by count",
      description: "High-frequency payees — rules pay off quickly here.",
      transactionIds: topMerchants.flatMap((c) => c.transactionIds),
      clusters: topMerchants,
    },
    {
      id: "fees_atm",
      title: "Fees & ATM / cash",
      description: "Bank fees, ATM withdrawals, and similar charge patterns.",
      transactionIds: sortNewestFirst(
        feesAtm.map((t) => t.id),
        byId,
      ),
      clusters: [],
    },
  ];

  return groups.filter((g) => g.transactionIds.length > 0 || g.clusters.length > 0);
}
