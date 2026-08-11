import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowLeftRight,
  ChevronDown,
  ChevronUp,
  Filter,
  Search,
  Sparkles,
  Tags,
  X,
} from "lucide-react";
import { api } from "../api/client";
import type {
  ApplyRulesResult,
  BootstrapRulesResult,
  Category,
  CategoryCoverage,
  CategoryRule,
  Transaction,
} from "../api/types";
import { Money } from "../components/Money";
import { EmptyState, PageLoader, Spinner } from "../components/Spinner";
import {
  countRuleMatches,
  sameVendorTransactionIds,
  suggestRuleFromTransactions,
  vendorDisplayName,
} from "../lib/ruleSuggest";
import { formatUsd } from "../lib/money";
import { cn } from "../lib/cn";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const MATCH_FIELDS = [
  "merchant",
  "description",
  "original_description",
  "source_institution",
] as const;
const MATCH_TYPES = ["contains", "exact", "starts_with", "regex"] as const;

function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

function txIsExpense(t: Transaction): boolean {
  const raw = t.amount_usd != null && t.amount_usd !== "" ? t.amount_usd : t.amount;
  const n = Number(raw);
  return Number.isFinite(n) && n < 0;
}

type TxSortKey = "date" | "description" | "category" | "source" | "amount";
type SortDir = "asc" | "desc";

const SORT_DEFAULT_DIR: Record<TxSortKey, SortDir> = {
  date: "desc",
  description: "asc",
  category: "asc",
  source: "asc",
  amount: "desc",
};

/** Prefer amount_usd for consistent size across mixed currencies; else statement amount. */
function txSortAmount(t: Transaction): number {
  const raw =
    t.amount_usd != null && t.amount_usd !== "" ? t.amount_usd : t.amount;
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

function txSortDescription(t: Transaction): string {
  return (t.merchant || t.description || "").trim();
}

type RuleDraft = {
  match_field: string;
  match_type: string;
  match_value: string;
  category_id: string;
  institution_scope: string;
  candidates: Array<{ value: string; count: number }>;
  /** Seeds used for “apply to same vendor” */
  seedTxs: Transaction[];
};

export function CategorizePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [cats, setCats] = useState<Category[]>([]);
  const [coverage, setCoverage] = useState<CategoryCoverage | null>(null);
  const [rules, setRules] = useState<CategoryRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkCategoryId, setBulkCategoryId] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [ruleDraft, setRuleDraft] = useState<RuleDraft | null>(null);
  const [ruleBusy, setRuleBusy] = useState(false);
  const [ruleMsg, setRuleMsg] = useState<string | null>(null);
  const [toolsBusy, setToolsBusy] = useState<string | null>(null);
  const [toolsMsg, setToolsMsg] = useState<string | null>(null);
  const [showRules, setShowRules] = useState(
    () => searchParams.get("panel") === "rules",
  );
  const [vendorBusy, setVendorBusy] = useState(false);
  const [latestBatchLabel, setLatestBatchLabel] = useState<string | null>(null);
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  const [editRuleDraft, setEditRuleDraft] = useState<{
    match_field: string;
    match_type: string;
    match_value: string;
    category_id: string;
    priority: number;
    is_active: boolean;
  } | null>(null);
  const [ruleActionBusy, setRuleActionBusy] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<TxSortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  /** H12: ignore stale responses when filters race */
  const loadGen = useRef(0);

  const dateFrom = searchParams.get("date_from") || "";
  const dateTo = searchParams.get("date_to") || "";
  const currency = searchParams.get("currency") || "";
  const hideTransfers = searchParams.get("hide_transfers") !== "0";
  const expensesOnly = searchParams.get("expenses_only") === "1";
  const categoryIdParam = searchParams.get("category_id") || "";
  const categoryIdsParam = searchParams.get("category_ids") || "";
  const lifeDomainParam = searchParams.get("life_domain") || "";
  const unconvertedOnly = searchParams.get("unconverted") === "1";
  const filterFlag = searchParams.get("filter") || "";
  const qFromUrl = searchParams.get("q") || "";

  // Local search text; re-sync when alert/drill-down sets ?q= in the URL
  const [q, setQ] = useState(qFromUrl);
  useEffect(() => {
    setQ(qFromUrl);
  }, [qFromUrl]);

  const txTableRef = useRef<HTMLDivElement | null>(null);
  const showAllLedger = searchParams.get("scope") === "all";
  /** No drill-down scope → default to latest import batch (faster than full ledger). */
  const useLatestBatch =
    !showAllLedger &&
    !dateFrom &&
    !dateTo &&
    !categoryIdParam &&
    !categoryIdsParam &&
    !lifeDomainParam &&
    !unconvertedOnly &&
    !filterFlag &&
    !qFromUrl;
  const drilldownActive = Boolean(
    dateFrom ||
      dateTo ||
      categoryIdParam ||
      categoryIdsParam ||
      lifeDomainParam ||
      unconvertedOnly ||
      filterFlag ||
      qFromUrl ||
      expensesOnly ||
      showAllLedger,
  );

  const multiCategoryIds = useMemo(
    () =>
      categoryIdsParam
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    [categoryIdsParam],
  );

  const patchParams = useCallback(
    (updates: Record<string, string | null>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(updates)) {
            if (value == null || value === "") next.delete(key);
            else next.set(key, value);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const load = useCallback(async (opts?: { quiet?: boolean }) => {
    const quiet = opts?.quiet ?? false;
    const gen = ++loadGen.current;
    // Keep existing UI visible while refreshing (avoids full-page blank on reloads)
    if (!quiet) setLoading(true);
    if (!quiet) setError(null);
    try {
      const apiCategoryId =
        categoryIdParam && isUuid(categoryIdParam) ? categoryIdParam : undefined;
      // Larger page when drill-down filters need client-side refinement
      const limit = showAllLedger || drilldownActive ? 3000 : 800;
      const [t, c, cov, r] = await Promise.all([
        api.transactions({
          limit,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          currency: currency || undefined,
          is_internal_transfer: hideTransfers ? false : undefined,
          category_id: apiCategoryId,
          latest_import_batch: useLatestBatch ? true : undefined,
        }),
        api.categories(),
        api.categoryCoverage(180),
        api.categoryRules(),
      ]);
      if (gen !== loadGen.current) return;
      setItems(t.items);
      setTotal(t.total);
      setCats(c.items);
      setCoverage(cov);
      setRules(r.items);
      if (t.latest_import_batch?.filenames?.length) {
        const names = t.latest_import_batch.filenames;
        setLatestBatchLabel(
          names.length === 1
            ? names[0]
            : `${names.length} files (${names.slice(0, 2).join(", ")}${names.length > 2 ? "…" : ""})`,
        );
      } else if (useLatestBatch) {
        setLatestBatchLabel(null);
      }
      setError(null);
    } catch (e) {
      if (gen !== loadGen.current) return;
      // Quiet refresh failures must not blank a loaded workspace
      if (quiet) return;
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      if (gen !== loadGen.current) return;
      if (!quiet) setLoading(false);
    }
  }, [
    currency,
    hideTransfers,
    dateFrom,
    dateTo,
    categoryIdParam,
    drilldownActive,
    useLatestBatch,
    showAllLedger,
  ]);

  useEffect(() => {
    void load();
  }, [load]);

  // After drill-down load, jump to the matching transaction list
  useEffect(() => {
    if (!drilldownActive || loading) return;
    const id = window.setTimeout(() => {
      txTableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);
    return () => window.clearTimeout(id);
  }, [
    drilldownActive,
    loading,
    dateFrom,
    dateTo,
    categoryIdParam,
    categoryIdsParam,
    lifeDomainParam,
    filterFlag,
    qFromUrl,
    unconvertedOnly,
    expensesOnly,
  ]);

  // Drop selection when the filtered universe changes
  useEffect(() => {
    setSelected(new Set());
  }, [dateFrom, dateTo, currency, hideTransfers, expensesOnly, categoryIdParam, categoryIdsParam, q]);

  const catMap = useMemo(() => {
    const m = new Map<string, Category>();
    cats.forEach((c) => m.set(c.id, c));
    return m;
  }, [cats]);

  const filtered = useMemo(() => {
    let rows = items;

    if (categoryIdParam === "uncategorized") {
      rows = rows.filter((t) => {
        if (!t.category_id) return true;
        const cat = catMap.get(t.category_id);
        return !cat || cat.life_domain === "Other";
      });
    } else if (multiCategoryIds.length > 0) {
      const set = new Set(multiCategoryIds);
      rows = rows.filter((t) => t.category_id != null && set.has(t.category_id));
    } else if (categoryIdParam && isUuid(categoryIdParam)) {
      rows = rows.filter((t) => t.category_id === categoryIdParam);
    }

    if (lifeDomainParam) {
      rows = rows.filter((t) => {
        if (!t.category_id) return lifeDomainParam === "Other";
        return catMap.get(t.category_id)?.life_domain === lifeDomainParam;
      });
    }

    if (filterFlag === "fixed") {
      rows = rows.filter((t) => {
        if (!t.category_id) return false;
        return catMap.get(t.category_id)?.necessity === "Fixed";
      });
    }

    if (filterFlag === "transfer_leak") {
      // Match backend alerts.transfer_leak_resolved: only unreviewed rows.
      // Peer "Transfer to NAME" already in living categories is intentional spend.
      const re =
        /\b(transfer|top-?up|topup|sent to|from revolut|to revolut|own account|me to me|me2me|p[rř]evod)\b/i;
      const transferDomains = new Set(["Transfers", "Investments"]);
      rows = rows.filter((t) => {
        if (t.is_internal_transfer) return false;
        if (t.category_id) {
          const cat = catMap.get(t.category_id);
          if (cat) {
            if (cat.is_transfer) return false;
            if (transferDomains.has(cat.life_domain)) return false;
            if (cat.life_domain && cat.life_domain !== "Other") return false;
            if (t.category_override) return false;
          }
        }
        const blob = [
          t.merchant,
          t.description,
          t.original_description,
          t.counterparty_name,
        ]
          .filter(Boolean)
          .join(" ");
        return re.test(blob);
      });
    }

    if (unconvertedOnly) {
      rows = rows.filter((t) => t.amount_usd == null || t.amount_usd === "");
    }

    if (expensesOnly) {
      rows = rows.filter(txIsExpense);
    }

    const needle = q.trim().toLowerCase();
    if (needle) {
      rows = rows.filter((t) => {
        const blob = [
          t.merchant,
          t.description,
          t.original_description,
          t.source_institution,
          t.external_id,
          t.counterparty_name,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return blob.includes(needle);
      });
    }

    return rows;
  }, [
    items,
    q,
    categoryIdParam,
    multiCategoryIds,
    expensesOnly,
    lifeDomainParam,
    unconvertedOnly,
    filterFlag,
    catMap,
  ]);

  const sortedRows = useMemo(() => {
    const rows = filtered.slice();
    const dir = sortDir === "asc" ? 1 : -1;
    rows.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "date":
          cmp = (a.booking_date || "").localeCompare(b.booking_date || "");
          break;
        case "description":
          cmp = txSortDescription(a).localeCompare(txSortDescription(b), undefined, {
            sensitivity: "base",
          });
          break;
        case "category": {
          const an = a.category_id
            ? catMap.get(a.category_id)?.name || ""
            : "Uncategorized";
          const bn = b.category_id
            ? catMap.get(b.category_id)?.name || ""
            : "Uncategorized";
          cmp = an.localeCompare(bn, undefined, { sensitivity: "base" });
          break;
        }
        case "source":
          cmp = (a.source_institution || "").localeCompare(
            b.source_institution || "",
            undefined,
            { sensitivity: "base" },
          );
          break;
        case "amount":
          cmp = txSortAmount(a) - txSortAmount(b);
          break;
      }
      if (cmp !== 0) return cmp * dir;
      return a.id.localeCompare(b.id);
    });
    return rows;
  }, [filtered, sortKey, sortDir, catMap]);

  function toggleSort(key: TxSortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDir(SORT_DEFAULT_DIR[key]);
  }

  const categoryFilterLabel = useMemo(() => {
    if (multiCategoryIds.length > 0) {
      // Chart residual rollup (outside top-N) — not life-domain "Other"
      return `Smaller categories (${multiCategoryIds.length})`;
    }
    if (categoryIdParam === "uncategorized") return "Uncategorized";
    if (categoryIdParam && isUuid(categoryIdParam)) {
      return catMap.get(categoryIdParam)?.name || "Category";
    }
    return null;
  }, [categoryIdParam, multiCategoryIds, catMap]);

  const hasActiveScope =
    Boolean(
      dateFrom ||
        dateTo ||
        categoryIdParam ||
        multiCategoryIds.length ||
        expensesOnly ||
        lifeDomainParam ||
        unconvertedOnly ||
        filterFlag ||
        q.trim() ||
        currency,
    ) || searchParams.get("hide_transfers") === "1";

  const allFilteredSelected =
    filtered.length > 0 && filtered.every((t) => selected.has(t.id));
  const someSelected = selected.size > 0;

  function clearScope() {
    setSearchParams({}, { replace: true });
    setQ("");
  }

  const filterChips = useMemo(() => {
    const chips: string[] = [];
    if (dateFrom || dateTo) {
      chips.push(`${dateFrom || "…"} → ${dateTo || "…"}`);
    }
    if (expensesOnly) chips.push("Expenses only");
    if (categoryFilterLabel) chips.push(categoryFilterLabel);
    if (lifeDomainParam) chips.push(`Domain: ${lifeDomainParam}`);
    if (filterFlag === "fixed") chips.push("Fixed costs");
    if (filterFlag === "transfer_leak") chips.push("Transfer-like (unflagged)");
    if (unconvertedOnly) chips.push("Missing FX");
    if (currency) chips.push(currency);
    if (q.trim()) chips.push(`Search: “${q.trim()}”`);
    if (hideTransfers) chips.push("Hide internal transfers");
    return chips;
  }, [
    dateFrom,
    dateTo,
    expensesOnly,
    categoryFilterLabel,
    lifeDomainParam,
    filterFlag,
    unconvertedOnly,
    currency,
    q,
    hideTransfers,
  ]);

  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAllFiltered() {
    if (allFilteredSelected) {
      setSelected(new Set());
      return;
    }
    setSelected(new Set(filtered.map((t) => t.id)));
  }

  function selectUncategorizedInView() {
    setSelected(new Set(filtered.filter((t) => !t.category_id).map((t) => t.id)));
  }

  function openRuleProposal(txs: Transaction[], categoryId: string) {
    const suggestion = suggestRuleFromTransactions(txs);
    setRuleMsg(null);
    if (!suggestion) {
      // Still offer same-vendor apply even without a rule seed
      setRuleDraft({
        match_field: "merchant",
        match_type: "contains",
        match_value: txs[0] ? vendorDisplayName(txs[0]) : "",
        category_id: categoryId,
        institution_scope: "",
        candidates: [],
        seedTxs: txs,
      });
      return;
    }
    setRuleDraft({
      match_field: suggestion.match_field,
      match_type: suggestion.match_type,
      match_value: suggestion.match_value,
      category_id: categoryId,
      institution_scope: suggestion.institution_scope || "",
      candidates: suggestion.candidates,
      seedTxs: txs,
    });
  }

  const sameVendorIds = useMemo(() => {
    if (!ruleDraft?.seedTxs?.length) return [] as string[];
    return sameVendorTransactionIds(items, ruleDraft.seedTxs, ruleDraft.category_id);
  }, [ruleDraft, items]);

  async function applySameVendorInView() {
    if (!ruleDraft || sameVendorIds.length === 0) return;
    setVendorBusy(true);
    try {
      const r = await api.bulkOverrideCategory(ruleDraft.category_id, sameVendorIds);
      const idSet = new Set(r.transaction_ids);
      setItems((prev) =>
        prev.map((t) =>
          idSet.has(t.id)
            ? { ...t, category_id: ruleDraft.category_id, category_override: true }
            : t,
        ),
      );
      setRuleMsg(`Applied to ${r.updated} other transaction(s) in this list.`);
    } catch (e) {
      setRuleMsg(e instanceof Error ? e.message : "Same-vendor apply failed");
    } finally {
      setVendorBusy(false);
    }
  }

  /** Apply current match pattern to the full ledger (outside current filters). */
  async function applyMatchGlobally(mode: "reclassify_non_override" | "fill_blanks" = "reclassify_non_override") {
    if (!ruleDraft || !ruleDraft.match_value.trim() || !ruleDraft.category_id) return;
    setVendorBusy(true);
    setRuleMsg(null);
    try {
      const r = await api.applyMatch({
        category_id: ruleDraft.category_id,
        match_field: ruleDraft.match_field,
        match_type: ruleDraft.match_type,
        match_value: ruleDraft.match_value.trim(),
        institution_scope: ruleDraft.institution_scope.trim() || null,
        mode,
        mark_override: true,
      });
      setRuleMsg(
        `Global apply: updated ${r.updated} of ${r.matched} matching tx(s) ` +
          `(scanned ${r.scanned}; skipped override ${r.skipped_override}, already ok ${r.skipped_already}).`,
      );
      // Soft reload keeps the table visible; server already wrote patches
      await load({ quiet: true });
    } catch (e) {
      setRuleMsg(e instanceof Error ? e.message : "Global apply failed");
    } finally {
      setVendorBusy(false);
    }
  }

  async function runTool(label: string, fn: () => Promise<string>) {
    setToolsBusy(label);
    setToolsMsg(null);
    try {
      const msg = await fn();
      setToolsMsg(msg);
      await load({ quiet: true });
    } catch (e) {
      setToolsMsg(e instanceof Error ? e.message : "Action failed");
    } finally {
      setToolsBusy(null);
    }
  }

  function categoryImpliesInternal(categoryId: string): boolean {
    const cat = catMap.get(categoryId);
    if (!cat) return false;
    if (cat.is_transfer) {
      const name = cat.name.toLowerCase();
      if (name.includes("internal") && !name.includes("external")) return true;
    }
    return false;
  }

  async function onOverride(txId: string, categoryId: string) {
    if (!categoryId) return;
    setSavingId(txId);
    try {
      await api.overrideCategory(categoryId, txId);
      const forceInternal = categoryImpliesInternal(categoryId);
      const tx = items.find((t) => t.id === txId);
      const patch = {
        category_id: categoryId,
        category_override: true as const,
        ...(forceInternal ? { is_internal_transfer: true } : {}),
      };
      setItems((prev) =>
        prev.map((t) => (t.id === txId ? { ...t, ...patch } : t)),
      );
      if (tx) openRuleProposal([{ ...tx, ...patch }], categoryId);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Override failed");
    } finally {
      setSavingId(null);
    }
  }

  async function applyBulkCategory() {
    if (!bulkCategoryId || selected.size === 0) return;
    setBulkBusy(true);
    try {
      const ids = [...selected];
      const r = await api.bulkOverrideCategory(bulkCategoryId, ids);
      const idSet = new Set(r.transaction_ids);
      const forceInternal = categoryImpliesInternal(bulkCategoryId);
      const patch = {
        category_id: bulkCategoryId,
        category_override: true as const,
        ...(forceInternal ? { is_internal_transfer: true } : {}),
      };
      setItems((prev) =>
        prev.map((t) => (idSet.has(t.id) ? { ...t, ...patch } : t)),
      );
      const affected = items.filter((t) => idSet.has(t.id));
      openRuleProposal(
        affected.map((t) => ({ ...t, ...patch })),
        bulkCategoryId,
      );
      setSelected(new Set());
    } catch (e) {
      alert(e instanceof Error ? e.message : "Bulk assign failed");
    } finally {
      setBulkBusy(false);
    }
  }

  async function saveRule(alsoApply: "none" | "blanks" | "all_matching") {
    if (!ruleDraft || !ruleDraft.match_value.trim() || !ruleDraft.category_id) return;
    setRuleBusy(true);
    setRuleMsg(null);
    try {
      await api.createCategoryRule({
        priority: 100,
        match_field: ruleDraft.match_field,
        match_type: ruleDraft.match_type,
        match_value: ruleDraft.match_value.trim(),
        category_id: ruleDraft.category_id,
        set_internal_transfer: false,
        institution_scope: ruleDraft.institution_scope.trim() || undefined,
        is_active: true,
        notes: "Created from Categorize workspace",
      });
      let applyNote = "";
      if (alsoApply === "blanks") {
        const applied = await api.applyRules();
        applyNote = ` · filled ${applied.filled} blank tx(s) only`;
        await load({ quiet: true });
      } else if (alsoApply === "all_matching") {
        const r = await api.applyMatch({
          category_id: ruleDraft.category_id,
          match_field: ruleDraft.match_field,
          match_type: ruleDraft.match_type,
          match_value: ruleDraft.match_value.trim(),
          institution_scope: ruleDraft.institution_scope.trim() || null,
          mode: "reclassify_non_override",
          mark_override: true,
        });
        applyNote =
          ` · reclassified ${r.updated} matching tx(s) across the full ledger` +
          ` (${r.matched} matched, ${r.skipped_override} overrides skipped)`;
        await load({ quiet: true });
      }
      setRuleMsg(`Rule saved${applyNote}.`);
      if (alsoApply !== "none") {
        setTimeout(() => {
          setRuleDraft(null);
          setRuleMsg(null);
        }, 2500);
      }
    } catch (e) {
      setRuleMsg(e instanceof Error ? e.message : "Could not save rule");
    } finally {
      setRuleBusy(false);
    }
  }

  const categorySelectValue =
    multiCategoryIds.length > 0
      ? "__multi__"
      : categoryIdParam === "uncategorized"
        ? "uncategorized"
        : isUuid(categoryIdParam)
          ? categoryIdParam
          : "";

  const rulePreviewCount = useMemo(() => {
    if (!ruleDraft) return 0;
    return countRuleMatches(items, {
      match_field: ruleDraft.match_field,
      match_type: ruleDraft.match_type,
      match_value: ruleDraft.match_value,
      institution_scope: ruleDraft.institution_scope || null,
      onlyWithoutOverride: true,
    });
  }, [ruleDraft, items]);

  const catsSorted = useMemo(
    () => cats.slice().sort((a, b) => a.name.localeCompare(b.name)),
    [cats],
  );

  if (loading && items.length === 0) {
    return <PageLoader label="Loading categorize workspace…" />;
  }
  if (error && items.length === 0) {
    return (
      <EmptyState
        title="Couldn’t load workspace"
        description={error}
        action={
          <button type="button" className="btn-primary" onClick={() => void load()}>
            Retry
          </button>
        }
      />
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Categorize</h1>
          <p className="text-sm text-ink-muted">
            Review transactions, assign categories, apply to the same vendor, and create
            rules for future imports
            {someSelected ? ` · ${selected.size} selected` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {hasActiveScope && (
            <button type="button" className="btn-ghost text-sm" onClick={clearScope}>
              <X className="h-4 w-4" /> Clear filters
            </button>
          )}
          <button
            type="button"
            className="btn-ghost text-sm"
            onClick={() => setShowRules((v) => !v)}
          >
            <Tags className="h-4 w-4" />
            {showRules ? "Hide rules" : `Rules (${rules.length})`}
          </button>
        </div>
      </div>

      {hasActiveScope && (
        <div className="sticky top-14 z-20 rounded-xl border border-brand/30 bg-slate-950/95 px-4 py-3 shadow-lg backdrop-blur-md">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold uppercase tracking-wide text-brand">
                Active filters · {filtered.length} matching transaction
                {filtered.length === 1 ? "" : "s"}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {filterChips.map((chip) => (
                  <span
                    key={chip}
                    className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-ink-muted"
                  >
                    {chip}
                  </span>
                ))}
              </div>
            </div>
            <button type="button" className="btn-ghost shrink-0 text-xs" onClick={clearScope}>
              <X className="h-3.5 w-3.5" /> Clear
            </button>
          </div>
        </div>
      )}

      {useLatestBatch && (
        <div className="rounded-xl border border-brand/25 bg-brand/10 px-4 py-3 text-sm text-ink">
          <span className="font-semibold text-brand">Latest import</span>
          <span className="text-ink-muted">
            {" "}
            · showing transactions from the most recent upload batch
            {latestBatchLabel ? ` (${latestBatchLabel})` : ""}
            {total ? ` · ${total} row${total === 1 ? "" : "s"}` : ""}
          </span>
          <button
            type="button"
            className="ml-3 text-xs font-medium text-brand hover:underline"
            onClick={() => patchParams({ scope: "all" })}
          >
            Show full ledger
          </button>
        </div>
      )}
      {showAllLedger && (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-xs text-ink-muted">
          Viewing full ledger (capped page).{" "}
          <button
            type="button"
            className="font-medium text-brand hover:underline"
            onClick={() => patchParams({ scope: null })}
          >
            Back to latest import
          </button>
        </div>
      )}

      {/* Coverage + tools */}
      <div className="grid gap-3 lg:grid-cols-3">
        {coverage && (
          <div className="card p-4 lg:col-span-1">
            <div className="label">Coverage (last {coverage.days}d expense)</div>
            <div
              className={cn(
                "text-2xl font-semibold",
                coverage.coverage_pct >= (coverage.target_pct ?? 90)
                  ? "text-ok"
                  : coverage.coverage_pct >= (coverage.amber_pct ?? 70)
                    ? "text-warn"
                    : "text-danger",
              )}
            >
              {coverage.coverage_pct.toFixed(0)}%
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className={cn(
                  "h-full rounded-full",
                  coverage.coverage_pct >= (coverage.target_pct ?? 90)
                    ? "bg-ok"
                    : coverage.coverage_pct >= (coverage.amber_pct ?? 70)
                      ? "bg-warn"
                      : "bg-danger",
                )}
                style={{
                  width: `${Math.min(100, Math.max(0, coverage.coverage_pct))}%`,
                }}
              />
            </div>
            <div className="mt-1 text-xs text-ink-faint">
              {formatUsd(coverage.expense_usd_categorized)} of{" "}
              {formatUsd(coverage.expense_usd_total)}
              {" · "}
              target {coverage.target_pct ?? 90}%
            </div>
            {coverage.windows?.["30d"] && (
              <div className="mt-1 text-[11px] text-ink-faint">
                30d: {coverage.windows["30d"].coverage_pct.toFixed(0)}% (
                {coverage.windows["30d"].status})
              </div>
            )}
          </div>
        )}
        {coverage && (
          <div className="card p-4 lg:col-span-1">
            <div className="label mb-1">Top uncategorized</div>
            <ul className="max-h-28 space-y-0.5 overflow-y-auto text-xs text-ink-muted">
              {coverage.top_uncategorized_merchants.slice(0, 6).map((m) => (
                <li key={m.label}>
                  <button
                    type="button"
                    className="flex w-full justify-between gap-2 text-left hover:text-brand"
                    onClick={() => {
                      setQ(m.label);
                      patchParams({ category_id: "uncategorized", category_ids: null });
                    }}
                  >
                    <span className="truncate">{m.label}</span>
                    <span className="shrink-0">{formatUsd(m.amount_usd)}</span>
                  </button>
                </li>
              ))}
              {!coverage.top_uncategorized_merchants.length && (
                <li className="text-ok">None in window</li>
              )}
            </ul>
          </div>
        )}
        <div className="card flex flex-col justify-center gap-2 p-4 lg:col-span-1">
          <div className="label">Tools</div>
          <div className="mb-1 flex flex-wrap gap-1.5">
            <button
              type="button"
              className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
              onClick={() => {
                const to = new Date();
                const from = new Date();
                from.setDate(to.getDate() - 29);
                const iso = (d: Date) => d.toISOString().slice(0, 10);
                patchParams({
                  date_from: iso(from),
                  date_to: iso(to),
                  category_id: "uncategorized",
                  category_ids: null,
                });
              }}
            >
              Uncategorized 30d
            </button>
            <button
              type="button"
              className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
              onClick={() => {
                const to = new Date();
                const from = new Date();
                from.setDate(to.getDate() - 29);
                const iso = (d: Date) => d.toISOString().slice(0, 10);
                patchParams({
                  date_from: iso(from),
                  date_to: iso(to),
                  category_id: null,
                  expenses_only: "1",
                });
              }}
            >
              Expenses 30d
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={!!toolsBusy}
              onClick={() =>
                void runTool("scan", async () => {
                  const r: BootstrapRulesResult = await api.bootstrapRules(true);
                  const a = r.apply as { filled?: number } | undefined;
                  return (
                    `Bootstrap +${r.rules_created} rules` +
                    (a?.filled != null ? ` · filled ${a.filled} blanks` : "")
                  );
                })
              }
            >
              {toolsBusy === "scan" ? "Working…" : "Scan & apply rules"}
            </button>
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={!!toolsBusy}
              onClick={() =>
                void runTool("apply", async () => {
                  const r: ApplyRulesResult = await api.applyRules();
                  return `Applied · filled ${r.filled}, unmatched ${r.unmatched}`;
                })
              }
            >
              {toolsBusy === "apply" ? "Working…" : "Apply blanks"}
            </button>
          </div>
          {toolsMsg && <p className="text-xs text-ink-muted">{toolsMsg}</p>}
        </div>
      </div>

      {(categoryFilterLabel || dateFrom || dateTo || expensesOnly) && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-brand/25 bg-brand/10 px-3 py-2 text-sm text-ink">
          <span className="text-xs font-semibold uppercase tracking-wide text-brand">
            From dashboard / filters
          </span>
          {categoryFilterLabel && (
            <span className="badge bg-white/10 text-ink">{categoryFilterLabel}</span>
          )}
          {(dateFrom || dateTo) && (
            <span className="badge bg-white/10 text-ink">
              {dateFrom || "…"} → {dateTo || "…"}
            </span>
          )}
          {expensesOnly && <span className="badge bg-white/10 text-ink">Expenses only</span>}
          {hideTransfers && (
            <span className="badge bg-white/10 text-ink">Transfers hidden</span>
          )}
          <span className="text-xs text-ink-muted">
            {filtered.length} txs · assign a better category · apply to same vendor · save a rule
          </span>
        </div>
      )}

      <div className="card flex flex-col gap-3 p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
            <input
              className="input pl-9"
              placeholder="Search merchant, description…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Filter className="h-4 w-4 text-ink-faint" />
            <select
              className="input w-auto py-2"
              value={currency}
              onChange={(e) => patchParams({ currency: e.target.value || null })}
            >
              <option value="">All currencies</option>
              <option value="USD">USD</option>
              <option value="CZK">CZK</option>
              <option value="EUR">EUR</option>
            </select>
            <select
              className="input w-auto max-w-[14rem] py-2"
              value={categorySelectValue}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "" || v === "__multi__") {
                  patchParams({ category_id: null, category_ids: null });
                } else if (v === "uncategorized") {
                  patchParams({ category_id: "uncategorized", category_ids: null });
                } else {
                  patchParams({ category_id: v, category_ids: null });
                }
              }}
            >
              <option value="">All categories</option>
              {multiCategoryIds.length > 0 && (
                <option value="__multi__">
                  Smaller categories ({multiCategoryIds.length})
                </option>
              )}
              <option value="uncategorized">Uncategorized</option>
              {catsSorted.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-ink-faint">
            From
            <input
              type="date"
              className="input mt-1 w-auto py-2"
              value={dateFrom}
              onChange={(e) => patchParams({ date_from: e.target.value || null })}
            />
          </label>
          <label className="text-xs text-ink-faint">
            To
            <input
              type="date"
              className="input mt-1 w-auto py-2"
              value={dateTo}
              onChange={(e) => patchParams({ date_to: e.target.value || null })}
            />
          </label>
          <label className="flex items-center gap-2 pb-2 text-sm text-ink-muted">
            <input
              type="checkbox"
              checked={hideTransfers}
              onChange={(e) =>
                patchParams({ hide_transfers: e.target.checked ? "1" : "0" })
              }
              className="rounded border-white/20"
            />
            Hide internal transfers
          </label>
          <label className="flex items-center gap-2 pb-2 text-sm text-ink-muted">
            <input
              type="checkbox"
              checked={expensesOnly}
              onChange={(e) =>
                patchParams({ expenses_only: e.target.checked ? "1" : null })
              }
              className="rounded border-white/20"
            />
            Expenses only
          </label>
          <button
            type="button"
            className="btn-ghost mb-0.5 text-xs"
            onClick={selectUncategorizedInView}
          >
            Select uncategorized in view
          </button>
        </div>
      </div>

      {/* Bulk action bar */}
      {someSelected && (
        <div className="sticky top-16 z-20 flex flex-col gap-3 rounded-xl border border-brand/30 bg-surface-raised/95 p-3 shadow-lg backdrop-blur-md sm:flex-row sm:items-center">
          <div className="text-sm font-medium text-ink">
            {selected.size} selected
          </div>
          <select
            className="input max-w-xs py-2 text-sm"
            value={bulkCategoryId}
            onChange={(e) => setBulkCategoryId(e.target.value)}
          >
            <option value="">Assign category…</option>
            {catsSorted.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn-primary"
            disabled={!bulkCategoryId || bulkBusy}
            onClick={() => void applyBulkCategory()}
          >
            {bulkBusy ? <Spinner className="h-4 w-4 border-t-slate-900" /> : null}
            Apply to selected
          </button>
          <button
            type="button"
            className="btn-ghost text-sm"
            onClick={() => setSelected(new Set())}
          >
            Clear selection
          </button>
        </div>
      )}

      {/* Rule proposal */}
      {ruleDraft && (
        <div className="card space-y-3 border-brand/25 p-4">
          <div className="flex items-start gap-2">
            <span className="rounded-lg bg-brand/15 p-2 text-brand">
              <Sparkles className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="font-semibold">Next: same vendor &amp; future rule</h2>
              <p className="text-sm text-ink-muted">
                Apply this category to other past transactions from the same merchant,
                then save a rule so future imports match automatically. Overrides stay locked.
              </p>
            </div>
            <button
              type="button"
              className="btn-ghost p-2"
              aria-label="Dismiss"
              onClick={() => setRuleDraft(null)}
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-3">
            <div className="text-sm font-medium text-ink">Apply beyond this list</div>
            <p className="text-xs text-ink-muted">
              The table only shows the current filter. Use global apply to update every
              matching transaction in your ledger (e.g. all Vodafone rows, any month).
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-primary text-sm"
                disabled={vendorBusy || !ruleDraft.match_value.trim()}
                onClick={() => void applyMatchGlobally("reclassify_non_override")}
              >
                {vendorBusy ? <Spinner className="h-4 w-4 border-t-slate-900" /> : null}
                Apply match to all similar (full ledger)
              </button>
              {sameVendorIds.length > 0 && (
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={vendorBusy}
                  onClick={() => void applySameVendorInView()}
                >
                  Only this list ({sameVendorIds.length} more from{" "}
                  {ruleDraft.seedTxs[0]
                    ? vendorDisplayName(ruleDraft.seedTxs[0])
                    : "vendor"}
                  )
                </button>
              )}
            </div>
          </div>

          {ruleDraft.candidates.length > 1 && (
            <label className="text-xs text-ink-faint">
              Suggested match values
              <select
                className="input mt-1 py-2 text-sm"
                value={ruleDraft.match_value}
                onChange={(e) =>
                  setRuleDraft((d) =>
                    d ? { ...d, match_value: e.target.value } : d,
                  )
                }
              >
                {ruleDraft.candidates.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.value} ({c.count})
                  </option>
                ))}
              </select>
            </label>
          )}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-ink-faint">
              Field
              <select
                className="input mt-1 py-2 text-sm"
                value={ruleDraft.match_field}
                onChange={(e) =>
                  setRuleDraft((d) =>
                    d ? { ...d, match_field: e.target.value } : d,
                  )
                }
              >
                {MATCH_FIELDS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-faint">
              Match
              <select
                className="input mt-1 py-2 text-sm"
                value={ruleDraft.match_type}
                onChange={(e) =>
                  setRuleDraft((d) =>
                    d ? { ...d, match_type: e.target.value } : d,
                  )
                }
              >
                {MATCH_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-faint sm:col-span-2">
              Value
              <input
                className="input mt-1 py-2 text-sm"
                value={ruleDraft.match_value}
                onChange={(e) =>
                  setRuleDraft((d) =>
                    d ? { ...d, match_value: e.target.value } : d,
                  )
                }
              />
            </label>
            <label className="text-xs text-ink-faint sm:col-span-2">
              Category
              <select
                className="input mt-1 py-2 text-sm"
                value={ruleDraft.category_id}
                onChange={(e) =>
                  setRuleDraft((d) =>
                    d ? { ...d, category_id: e.target.value } : d,
                  )
                }
              >
                {catsSorted.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-faint sm:col-span-2">
              Institution scope (optional)
              <input
                className="input mt-1 py-2 text-sm"
                placeholder="e.g. Revolut — leave blank for all"
                value={ruleDraft.institution_scope}
                onChange={(e) =>
                  setRuleDraft((d) =>
                    d ? { ...d, institution_scope: e.target.value } : d,
                  )
                }
              />
            </label>
          </div>

          <p className="text-xs text-ink-muted">
            Preview on loaded list: would match{" "}
            <span className="font-semibold text-ink">{rulePreviewCount}</span> non-override
            transaction(s).
          </p>

          {ruleMsg && <p className="text-sm text-brand">{ruleMsg}</p>}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={ruleBusy || !ruleDraft.match_value.trim()}
              onClick={() => void saveRule("all_matching")}
            >
              {ruleBusy ? <Spinner className="h-4 w-4 border-t-slate-900" /> : null}
              Save rule &amp; apply to all matching
            </button>
            <button
              type="button"
              className="btn-secondary"
              disabled={ruleBusy || !ruleDraft.match_value.trim()}
              onClick={() => void saveRule("none")}
            >
              Save rule only
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={ruleBusy || !ruleDraft.match_value.trim()}
              onClick={() => void saveRule("blanks")}
            >
              Save rule &amp; blanks only
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={ruleBusy}
              onClick={() => setRuleDraft(null)}
            >
              Not now
            </button>
          </div>
        </div>
      )}

      <div ref={txTableRef} className="scroll-mt-28 text-xs text-ink-faint">
        {filtered.length} shown
        {total !== filtered.length ? ` · ${total} from server` : ""}
        {hasActiveScope ? " · filtered from alert / chart drill-down" : ""}
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          title="No transactions match these filters"
          description="Clear filters or widen the date range."
        />
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="border-b border-white/5 bg-white/[0.02] text-xs uppercase tracking-wide text-ink-faint">
                <tr>
                  <th className="w-10 px-3 py-3">
                    <input
                      type="checkbox"
                      className="rounded border-white/20"
                      checked={allFilteredSelected}
                      ref={(el) => {
                        if (el) {
                          el.indeterminate = someSelected && !allFilteredSelected;
                        }
                      }}
                      onChange={toggleAllFiltered}
                      aria-label="Select all in view"
                    />
                  </th>
                  {(
                    [
                      { key: "date", label: "Date", align: "left" },
                      { key: "description", label: "Description", align: "left" },
                      { key: "category", label: "Category", align: "left" },
                      { key: "source", label: "Source", align: "left" },
                      { key: "amount", label: "Amount", align: "right" },
                    ] as const
                  ).map((col) => {
                    const active = sortKey === col.key;
                    const ariaSort = active
                      ? sortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none";
                    return (
                      <th
                        key={col.key}
                        className={cn(
                          "px-4 py-3 font-medium",
                          col.align === "right" && "text-right",
                        )}
                        aria-sort={ariaSort}
                      >
                        <button
                          type="button"
                          onClick={() => toggleSort(col.key)}
                          className={cn(
                            "inline-flex items-center gap-1 font-medium uppercase tracking-wide transition-colors",
                            col.align === "right" && "w-full justify-end",
                            active
                              ? "text-ink"
                              : "text-ink-faint hover:text-ink-muted",
                          )}
                        >
                          {col.label}
                          {active ? (
                            sortDir === "asc" ? (
                              <ChevronUp className="h-3.5 w-3.5 shrink-0" aria-hidden />
                            ) : (
                              <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden />
                            )
                          ) : (
                            <span className="inline-block h-3.5 w-3.5 shrink-0 opacity-0" aria-hidden />
                          )}
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {sortedRows.map((t) => {
                  const cat = t.category_id ? catMap.get(t.category_id) : undefined;
                  const isSel = selected.has(t.id);
                  return (
                    <tr
                      key={t.id}
                      className={cn(
                        "hover:bg-white/[0.02]",
                        isSel && "bg-brand/5",
                      )}
                    >
                      <td className="px-3 py-3">
                        <input
                          type="checkbox"
                          className="rounded border-white/20"
                          checked={isSel}
                          onChange={() => toggleOne(t.id)}
                          aria-label={`Select ${t.merchant || t.description || t.id}`}
                        />
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-ink-muted">
                        {t.booking_date}
                      </td>
                      <td className="max-w-xs px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-ink">
                            {t.merchant || t.description || "—"}
                          </span>
                          {t.is_internal_transfer && (
                            <span className="badge bg-brand/15 text-brand">
                              <ArrowLeftRight className="mr-1 h-3 w-3" />
                              Internal
                            </span>
                          )}
                          {t.category_override && (
                            <span className="badge bg-warn/15 text-warn">Override</span>
                          )}
                        </div>
                        {t.description && t.merchant && (
                          <div className="truncate text-xs text-ink-faint">{t.description}</div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <select
                            className="input max-w-[11rem] py-1.5 text-xs"
                            value={t.category_id || ""}
                            disabled={savingId === t.id}
                            onChange={(e) => void onOverride(t.id, e.target.value)}
                          >
                            <option value="">Uncategorized</option>
                            {catsSorted.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))}
                          </select>
                          {savingId === t.id && <Spinner className="h-3.5 w-3.5" />}
                        </div>
                        {cat && (
                          <div className="mt-0.5 text-[10px] text-ink-faint">
                            {cat.necessity} · {cat.life_domain}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-ink-muted">{t.source_institution}</td>
                      <td className="px-4 py-3 text-right">
                        <Money
                          amount={t.amount}
                          currency={t.currency}
                          amountCzk={t.amount_czk}
                          amountUsd={t.amount_usd}
                          signed
                          align="right"
                          size="sm"
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Collapsible rules admin */}
      <div className="card overflow-hidden">
        <button
          type="button"
          className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold"
          onClick={() => setShowRules((v) => !v)}
        >
          <span className="flex items-center gap-2">
            <Tags className="h-4 w-4 text-brand" />
            Active rules ({rules.filter((r) => r.is_active).length})
          </span>
          <ChevronDown
            className={cn("h-4 w-4 transition", showRules ? "rotate-180" : "")}
          />
        </button>
        {showRules && (
          <div className="border-t border-white/5">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="text-xs text-ink-faint">
                  <tr>
                    <th className="px-4 py-2 font-medium">Prio</th>
                    <th className="px-4 py-2 font-medium">Match</th>
                    <th className="px-4 py-2 font-medium">Category</th>
                    <th className="px-4 py-2 font-medium">Active</th>
                    <th className="px-4 py-2 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {rules
                    .slice()
                    .sort((a, b) => a.priority - b.priority)
                    .map((r) => (
                      <tr key={r.id} className={!r.is_active ? "opacity-50" : undefined}>
                        {editingRuleId === r.id && editRuleDraft ? (
                          <>
                            <td className="px-4 py-2">
                              <input
                                type="number"
                                className="input w-16 py-1 text-xs"
                                value={editRuleDraft.priority}
                                onChange={(e) =>
                                  setEditRuleDraft((d) =>
                                    d
                                      ? { ...d, priority: Number(e.target.value) || 0 }
                                      : d,
                                  )
                                }
                              />
                            </td>
                            <td className="px-4 py-2 space-y-1">
                              <div className="flex flex-wrap gap-1">
                                <select
                                  className="input max-w-[7rem] py-1 text-[11px]"
                                  value={editRuleDraft.match_field}
                                  onChange={(e) =>
                                    setEditRuleDraft((d) =>
                                      d ? { ...d, match_field: e.target.value } : d,
                                    )
                                  }
                                >
                                  <option value="merchant">merchant</option>
                                  <option value="description">description</option>
                                  <option value="original_description">
                                    original_description
                                  </option>
                                  <option value="counterparty_name">
                                    counterparty_name
                                  </option>
                                  <option value="source_institution">
                                    source_institution
                                  </option>
                                </select>
                                <select
                                  className="input max-w-[6rem] py-1 text-[11px]"
                                  value={editRuleDraft.match_type}
                                  onChange={(e) =>
                                    setEditRuleDraft((d) =>
                                      d ? { ...d, match_type: e.target.value } : d,
                                    )
                                  }
                                >
                                  <option value="contains">contains</option>
                                  <option value="exact">exact</option>
                                  <option value="exact_case">exact_case</option>
                                  <option value="starts_with">starts_with</option>
                                  <option value="regex">regex</option>
                                </select>
                              </div>
                              <input
                                className="input w-full py-1 text-xs"
                                value={editRuleDraft.match_value}
                                onChange={(e) =>
                                  setEditRuleDraft((d) =>
                                    d ? { ...d, match_value: e.target.value } : d,
                                  )
                                }
                              />
                            </td>
                            <td className="px-4 py-2">
                              <select
                                className="input max-w-[10rem] py-1 text-xs"
                                value={editRuleDraft.category_id}
                                onChange={(e) =>
                                  setEditRuleDraft((d) =>
                                    d ? { ...d, category_id: e.target.value } : d,
                                  )
                                }
                              >
                                {catsSorted.map((c) => (
                                  <option key={c.id} value={c.id}>
                                    {c.name}
                                  </option>
                                ))}
                              </select>
                            </td>
                            <td className="px-4 py-2">
                              <label className="flex items-center gap-1 text-xs">
                                <input
                                  type="checkbox"
                                  checked={editRuleDraft.is_active}
                                  onChange={(e) =>
                                    setEditRuleDraft((d) =>
                                      d ? { ...d, is_active: e.target.checked } : d,
                                    )
                                  }
                                />
                                Active
                              </label>
                            </td>
                            <td className="px-4 py-2 text-right">
                              <div className="flex justify-end gap-1">
                                <button
                                  type="button"
                                  className="btn-primary px-2 py-0.5 text-[11px]"
                                  disabled={ruleActionBusy === r.id}
                                  onClick={() => {
                                    if (!editRuleDraft) return;
                                    setRuleActionBusy(r.id);
                                    void (async () => {
                                      try {
                                        await api.updateCategoryRule(r.id, {
                                          priority: editRuleDraft.priority,
                                          match_field: editRuleDraft.match_field,
                                          match_type: editRuleDraft.match_type,
                                          match_value: editRuleDraft.match_value,
                                          category_id: editRuleDraft.category_id,
                                          is_active: editRuleDraft.is_active,
                                        } as Partial<CategoryRule>);
                                        setEditingRuleId(null);
                                        setEditRuleDraft(null);
                                        await load({ quiet: true });
                                      } catch (e) {
                                        setToolsMsg(
                                          e instanceof Error
                                            ? e.message
                                            : "Rule update failed",
                                        );
                                      } finally {
                                        setRuleActionBusy(null);
                                      }
                                    })();
                                  }}
                                >
                                  Save
                                </button>
                                <button
                                  type="button"
                                  className="btn-ghost px-2 py-0.5 text-[11px]"
                                  onClick={() => {
                                    setEditingRuleId(null);
                                    setEditRuleDraft(null);
                                  }}
                                >
                                  Cancel
                                </button>
                              </div>
                            </td>
                          </>
                        ) : (
                          <>
                            <td className="px-4 py-2 font-mono text-xs">{r.priority}</td>
                            <td className="px-4 py-2">
                              <div className="text-xs text-ink-faint">
                                {r.match_field} · {r.match_type}
                              </div>
                              <div className="font-medium">{r.match_value}</div>
                            </td>
                            <td className="px-4 py-2">
                              {catMap.get(r.category_id)?.name ||
                                r.category_id.slice(0, 8)}
                            </td>
                            <td className="px-4 py-2">{r.is_active ? "Yes" : "No"}</td>
                            <td className="px-4 py-2 text-right">
                              <div className="flex justify-end gap-1">
                                <button
                                  type="button"
                                  className="btn-secondary px-2 py-0.5 text-[11px]"
                                  onClick={() => {
                                    setEditingRuleId(r.id);
                                    setEditRuleDraft({
                                      match_field: r.match_field,
                                      match_type: r.match_type,
                                      match_value: r.match_value,
                                      category_id: r.category_id,
                                      priority: r.priority,
                                      is_active: r.is_active,
                                    });
                                  }}
                                >
                                  Edit
                                </button>
                                <button
                                  type="button"
                                  className="btn-ghost px-2 py-0.5 text-[11px] text-danger"
                                  disabled={ruleActionBusy === r.id}
                                  onClick={() => {
                                    if (
                                      !window.confirm(
                                        `Deactivate rule “${r.match_value}”?`,
                                      )
                                    ) {
                                      return;
                                    }
                                    setRuleActionBusy(r.id);
                                    void (async () => {
                                      try {
                                        await api.deleteCategoryRule(r.id);
                                        await load({ quiet: true });
                                      } catch (e) {
                                        setToolsMsg(
                                          e instanceof Error
                                            ? e.message
                                            : "Rule delete failed",
                                        );
                                      } finally {
                                        setRuleActionBusy(null);
                                      }
                                    })();
                                  }}
                                >
                                  Remove
                                </button>
                              </div>
                            </td>
                          </>
                        )}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
