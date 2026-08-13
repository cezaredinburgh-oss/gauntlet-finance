import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowLeftRight,
  ChevronDown,
  ChevronUp,
  Filter,
  Layers,
  Search,
  Sparkles,
  Tags,
  Undo2,
  X,
} from "lucide-react";
import { api } from "../api/client";
import type {
  AiCategorySuggestion,
  ApplyRulesResult,
  BootstrapRulesResult,
  Category,
  CategoryCoverage,
  CategoryRule,
  Transaction,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Money } from "../components/Money";
import { EmptyState, PageLoader, Spinner } from "../components/Spinner";
import {
  createUndoEntry,
  isUndoValid,
  snapshotFromTx,
  type UndoEntry,
} from "../lib/categorizeUndo";
import {
  analyseRuleAgainstEvidence,
  refineMatchValueFromEvidence,
} from "../lib/ruleExplain";
import {
  countRuleMatches,
  findSimilarTransactions,
  suggestRuleFromTransactions,
  vendorDisplayName,
  type RuleSuggestion,
} from "../lib/ruleSuggest";
import { buildSmartGroups } from "../lib/smartGroups";
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

const MODES = [
  { id: "review", label: "Review" },
  { id: "groups", label: "Groups" },
  { id: "ai", label: "AI assist" },
  { id: "rules", label: "Rules" },
] as const;

type WorkspaceMode = (typeof MODES)[number]["id"];

type SimFlowPhase =
  | "idle"
  | "offer_similar"
  | "reviewing_similar"
  | "offer_rule";

type FilterSnapshot = {
  search: string;
  q: string;
};

type SimFlow = {
  phase: SimFlowPhase;
  categoryId: string;
  seedIds: string[];
  /** Tx ids assigned as seeds (category already applied). */
  seedSnapshots: Transaction[];
  /** Similar candidates found when entering reviewing_similar. */
  similarIds: string[];
  /** Similar candidates the user unchecked during review (exclusions for rule). */
  excludedIds: string[];
  /** Also-assigned similar ids after group assign. */
  acceptedSimilarIds: string[];
  filterSnapshot: FilterSnapshot | null;
};

type RuleDraft = {
  match_field: string;
  match_type: string;
  match_value: string;
  category_id: string;
  institution_scope: string;
  candidates: Array<{ value: string; count: number }>;
  seedTxs: Transaction[];
  plainEnglish: string;
  warning: string | null;
};

const IDLE_SIM: SimFlow = {
  phase: "idle",
  categoryId: "",
  seedIds: [],
  seedSnapshots: [],
  similarIds: [],
  excludedIds: [],
  acceptedSimilarIds: [],
  filterSnapshot: null,
};

function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

function txIsExpense(t: Transaction): boolean {
  const raw = t.amount_usd != null && t.amount_usd !== "" ? t.amount_usd : t.amount;
  const n = Number(raw);
  return Number.isFinite(n) && n < 0;
}

/** Match backend `merchant_key`: `m:{merchant lower}` or `d:{desc first 48 lower}`. */
function merchantKeyFromTx(t: Transaction): string | null {
  const merchant = (t.merchant || "").trim().replace(/\s+/g, " ");
  if (merchant) return `m:${merchant.toLowerCase()}`;
  const desc = (t.description || "").trim().replace(/\s+/g, " ");
  if (!desc) return null;
  const d = desc.length > 48 ? desc.slice(0, 48) : desc;
  return `d:${d.toLowerCase()}`;
}

/** True when tx has a real category (not blank / Other residual). */
function txHasRealCategory(
  t: Transaction,
  catMap: Map<string, Category>,
): boolean {
  if (!t.category_id) return false;
  const cat = catMap.get(t.category_id);
  if (!cat) return false;
  if (cat.life_domain === "Other") return false;
  const name = (cat.name || "").trim().toLowerCase();
  if (name === "other" || name === "uncategorized") return false;
  return true;
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

function modeFromSearchParams(params: URLSearchParams): WorkspaceMode {
  if (params.get("panel") === "rules") return "rules";
  const m = params.get("mode");
  if (m === "groups" || m === "ai" || m === "rules" || m === "review") return m;
  return "review";
}

export function CategorizePage() {
  const { isReadOnly, user } = useAuth();
  const isSandboxDemo = Boolean(
    user?.is_demo && (user?.demo_kind === "sandbox" || user?.demo_kind === "lab"),
  );
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
  const [aiSuggestions, setAiSuggestions] = useState<AiCategorySuggestion[]>([]);
  const [aiSkippedKeys, setAiSkippedKeys] = useState<string[]>([]);
  /** Merchant keys already assigned via AI/guided flow — excluded from future suggest. */
  const [aiAppliedKeys, setAiAppliedKeys] = useState<string[]>([]);
  const [aiHints, setAiHints] = useState<Record<string, string>>({});
  const [aiCategoryPicks, setAiCategoryPicks] = useState<Record<string, string>>(
    {},
  );
  const [aiMsg, setAiMsg] = useState<string | null>(null);
  const [mode, setMode] = useState<WorkspaceMode>(() =>
    modeFromSearchParams(searchParams),
  );
  const [simFlow, setSimFlow] = useState<SimFlow>(IDLE_SIM);
  /** Local id allowlist for similar-review / groups focus. */
  const [focusIds, setFocusIds] = useState<string[] | null>(null);
  const [undoEntry, setUndoEntry] = useState<UndoEntry | null>(null);
  const [undoBusy, setUndoBusy] = useState(false);
  const [undoTick, setUndoTick] = useState(0);
  const [ruleAdvancedOpen, setRuleAdvancedOpen] = useState(false);
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
  const [latestBatchLabel, setLatestBatchLabel] = useState<string | null>(null);
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

  // Keep mode in sync when panel=rules arrives from outside
  useEffect(() => {
    if (searchParams.get("panel") === "rules") {
      setMode("rules");
    }
  }, [searchParams]);

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

  function setWorkspaceMode(next: WorkspaceMode) {
    setMode(next);
    if (next === "rules") {
      patchParams({ panel: "rules", mode: null });
    } else {
      patchParams({
        panel: null,
        mode: next === "review" ? null : next,
      });
    }
  }

  const load = useCallback(async (opts?: { quiet?: boolean }): Promise<Transaction[] | undefined> => {
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
      if (gen !== loadGen.current) return undefined;
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
      return t.items;
    } catch (e) {
      if (gen !== loadGen.current) return undefined;
      // Quiet refresh failures must not blank a loaded workspace
      if (quiet) return undefined;
      setError(e instanceof Error ? e.message : "Failed to load");
      return undefined;
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

  async function refreshCoverage() {
    try {
      const cov = await api.categoryCoverage(180);
      setCoverage(cov);
    } catch {
      // Best-effort; mutations already succeeded
    }
  }

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

  // Drop selection when the filtered universe changes — except during similar review
  useEffect(() => {
    if (simFlow.phase === "reviewing_similar") return;
    setSelected(new Set());
  }, [
    dateFrom,
    dateTo,
    currency,
    hideTransfers,
    expensesOnly,
    categoryIdParam,
    categoryIdsParam,
    q,
    simFlow.phase,
  ]);

  // Tick undo toast so it disappears when TTL ends
  useEffect(() => {
    if (!undoEntry) return;
    const ms = Math.max(0, undoEntry.expiresAt - Date.now());
    const id = window.setTimeout(() => setUndoTick((n) => n + 1), ms + 30);
    return () => window.clearTimeout(id);
  }, [undoEntry]);

  const undoVisible = useMemo(
    () => isUndoValid(undoEntry),
    [undoEntry, undoTick],
  );

  const catMap = useMemo(() => {
    const m = new Map<string, Category>();
    cats.forEach((c) => m.set(c.id, c));
    return m;
  }, [cats]);

  const filtered = useMemo(() => {
    let rows = items;

    // Similar-review: show seed + candidates only (ignore category filters so
    // just-assigned seeds stay visible under "uncategorized" scope).
    if (
      simFlow.phase === "reviewing_similar" &&
      focusIds &&
      focusIds.length > 0
    ) {
      const allow = new Set(focusIds);
      return rows.filter((t) => allow.has(t.id));
    }

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

    // Groups / AI focus: intersect allowlist with filtered rows
    if (focusIds && focusIds.length > 0) {
      const allow = new Set(focusIds);
      rows = rows.filter((t) => allow.has(t.id));
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
    focusIds,
    simFlow.phase,
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
        currency ||
        (focusIds && focusIds.length > 0),
    ) || searchParams.get("hide_transfers") === "1";

  const allFilteredSelected =
    filtered.length > 0 && filtered.every((t) => selected.has(t.id));
  const someSelected = selected.size > 0;

  function clearScope() {
    setSearchParams({}, { replace: true });
    setQ("");
    setFocusIds(null);
    setMode("review");
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
    if (focusIds && focusIds.length > 0) {
      chips.push(`Focus: ${focusIds.length} tx`);
    }
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
    focusIds,
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

  const smartGroups = useMemo(
    () => buildSmartGroups(items, cats),
    [items, cats],
  );

  function pushUndo(label: string, previousTxs: Transaction[]) {
    const previous: UndoEntry["previous"] = {};
    // Merge with still-valid prior entry so multi-step guided assigns undo together
    if (undoEntry && isUndoValid(undoEntry)) {
      Object.assign(previous, undoEntry.previous);
    }
    for (const t of previousTxs) {
      // Keep first snapshot per id (pre-assign state)
      if (!previous[t.id]) {
        previous[t.id] = snapshotFromTx(t);
      }
    }
    if (Object.keys(previous).length === 0) return;
    setUndoEntry(createUndoEntry(label, previous));
  }

  /**
   * Drop AI suggestions whose clusters are fully categorized (not Other), or
   * whose merchant_key was just assigned. Returns keys marked applied.
   */
  function pruneAiSuggestions(
    assignedTxIds: string[],
    itemsAfter: Transaction[],
  ): string[] {
    const assignedSet = new Set(assignedTxIds);
    const removeKeys = new Set<string>();
    for (const id of assignedSet) {
      const t = itemsAfter.find((x) => x.id === id);
      const k = t ? merchantKeyFromTx(t) : null;
      if (k) removeKeys.add(k);
    }
    const byId = new Map(itemsAfter.map((t) => [t.id, t]));
    for (const s of aiSuggestions) {
      if (removeKeys.has(s.merchant_key)) continue;
      if (s.transaction_ids.length === 0) continue;
      const allFilled = s.transaction_ids.every((id) => {
        const t = byId.get(id);
        if (!t) return false;
        return txHasRealCategory(t, catMap);
      });
      if (allFilled) removeKeys.add(s.merchant_key);
    }
    if (removeKeys.size === 0) return [];
    setAiSuggestions((prev) =>
      prev.filter((s) => !removeKeys.has(s.merchant_key)),
    );
    setAiAppliedKeys((prev) => {
      const next = [...prev];
      for (const k of removeKeys) {
        if (!next.includes(k)) next.push(k);
      }
      return next;
    });
    return [...removeKeys];
  }

  async function performUndo() {
    if (!undoEntry || !isUndoValid(undoEntry)) {
      setUndoEntry(null);
      return;
    }
    setUndoBusy(true);
    try {
      const payload = Object.entries(undoEntry.previous).map(([id, snap]) => ({
        transaction_id: id,
        category_id: snap.category_id,
        category_override: snap.category_override,
        is_internal_transfer: snap.is_internal_transfer,
      }));
      await api.restoreAssignments(payload);
      const prevMap = undoEntry.previous;
      setItems((prev) =>
        prev.map((t) => {
          const snap = prevMap[t.id];
          if (!snap) return t;
          return {
            ...t,
            category_id: snap.category_id,
            category_override: snap.category_override,
            is_internal_transfer: snap.is_internal_transfer,
          };
        }),
      );
      setUndoEntry(null);
      setSimFlow(IDLE_SIM);
      setRuleDraft(null);
      setFocusIds(null);
      void refreshCoverage();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Undo failed");
    } finally {
      setUndoBusy(false);
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

  function buildRuleDraftFromEvidence(
    included: Transaction[],
    excluded: Transaction[],
    categoryId: string,
  ): RuleDraft {
    const base = suggestRuleFromTransactions(included);
    const suggestion = base
      ? refineMatchValueFromEvidence(base, included, excluded)
      : {
          match_field: "merchant" as const,
          match_type: "contains" as const,
          match_value: included[0] ? vendorDisplayName(included[0]) : "",
          institution_scope: null as string | null,
          candidates: [] as Array<{ value: string; count: number }>,
        };
    const categoryName = catMap.get(categoryId)?.name || "category";
    const analysis = analyseRuleAgainstEvidence(
      suggestion,
      categoryName,
      included,
      excluded,
    );
    return {
      match_field: suggestion.match_field,
      match_type: suggestion.match_type,
      match_value: suggestion.match_value,
      category_id: categoryId,
      institution_scope: suggestion.institution_scope || "",
      candidates: suggestion.candidates || [],
      seedTxs: included,
      plainEnglish: analysis.plainEnglish,
      warning: analysis.warning,
    };
  }

  function enterOfferRule(
    seeds: Transaction[],
    categoryId: string,
    acceptedSimilar: Transaction[] = [],
    excluded: Transaction[] = [],
  ) {
    const included = [...seeds, ...acceptedSimilar];
    const draft = buildRuleDraftFromEvidence(included, excluded, categoryId);
    setRuleDraft(draft);
    setRuleMsg(null);
    setRuleAdvancedOpen(false);
    setSimFlow({
      phase: "offer_rule",
      categoryId,
      seedIds: seeds.map((t) => t.id),
      seedSnapshots: seeds,
      similarIds: [],
      excludedIds: excluded.map((t) => t.id),
      acceptedSimilarIds: acceptedSimilar.map((t) => t.id),
      filterSnapshot: null,
    });
    setFocusIds(null);
  }

  function startGuidedAfterAssign(seeds: Transaction[], categoryId: string) {
    // Stay on current mode (groups/ai/review) — workbench embeds when needed
    setRuleDraft(null);
    setRuleMsg(null);
    setSimFlow({
      phase: "offer_similar",
      categoryId,
      seedIds: seeds.map((t) => t.id),
      seedSnapshots: seeds,
      similarIds: [],
      excludedIds: [],
      acceptedSimilarIds: [],
      filterSnapshot: null,
    });
  }

  function onOfferSimilarYes() {
    const seeds = simFlow.seedSnapshots;
    if (!seeds.length) return;
    const similar = findSimilarTransactions(items, seeds, {
      sameAmountSign: true,
    });
    if (similar.length === 0) {
      // Nothing similar in the loaded list — go straight to rule offer
      enterOfferRule(seeds, simFlow.categoryId, [], []);
      return;
    }
    const snapshot: FilterSnapshot = {
      search: searchParams.toString(),
      q,
    };
    const seedIds = seeds.map((t) => t.id);
    const similarIds = similar.map((t) => t.id);
    setFocusIds([...seedIds, ...similarIds]);
    // Pre-select similar candidates (not seeds)
    setSelected(new Set(similarIds));
    setSimFlow((prev) => ({
      ...prev,
      phase: "reviewing_similar",
      similarIds,
      excludedIds: [],
      filterSnapshot: snapshot,
    }));
    window.setTimeout(() => {
      txTableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
  }

  function restoreFilterSnapshot(snapshot: FilterSnapshot | null) {
    if (snapshot) {
      setSearchParams(new URLSearchParams(snapshot.search), { replace: true });
      setQ(snapshot.q);
    }
    setFocusIds(null);
  }

  function onOfferSimilarNo() {
    enterOfferRule(simFlow.seedSnapshots, simFlow.categoryId, [], []);
  }

  function onCancelSimilarReview() {
    restoreFilterSnapshot(simFlow.filterSnapshot);
    setSelected(new Set());
    enterOfferRule(simFlow.seedSnapshots, simFlow.categoryId, [], []);
  }

  async function onAssignSimilarSelected() {
    if (!simFlow.categoryId || selected.size === 0) {
      // Nothing selected — treat as skip to rule with seeds only
      restoreFilterSnapshot(simFlow.filterSnapshot);
      setSelected(new Set());
      enterOfferRule(simFlow.seedSnapshots, simFlow.categoryId, [], []);
      return;
    }
    const ids = [...selected];
    const seedIdSet = new Set(simFlow.seedIds);
    // Only assign non-seed selection (similar candidates)
    const toAssign = ids.filter((id) => !seedIdSet.has(id));
    const similarIdSet = new Set(simFlow.similarIds);
    const excluded = simFlow.similarIds.filter(
      (id) => !selected.has(id) && similarIdSet.has(id),
    );
    const excludedTxs = items.filter((t) => excluded.includes(t.id));

    if (toAssign.length === 0) {
      restoreFilterSnapshot(simFlow.filterSnapshot);
      setSelected(new Set());
      enterOfferRule(simFlow.seedSnapshots, simFlow.categoryId, [], excludedTxs);
      return;
    }

    setBulkBusy(true);
    try {
      const previousTxs = items.filter((t) => toAssign.includes(t.id));
      const catName = catMap.get(simFlow.categoryId)?.name || "category";
      pushUndo(`Assigned ${catName} to ${toAssign.length}`, previousTxs);

      const r = await api.bulkOverrideCategory(simFlow.categoryId, toAssign);
      const idSet = new Set(r.transaction_ids);
      const forceInternal = categoryImpliesInternal(simFlow.categoryId);
      const patch = {
        category_id: simFlow.categoryId,
        category_override: true as const,
        ...(forceInternal ? { is_internal_transfer: true } : {}),
      };
      const nextItems = items.map((t) =>
        idSet.has(t.id) ? { ...t, ...patch } : t,
      );
      setItems(nextItems);
      const accepted = previousTxs
        .filter((t) => idSet.has(t.id))
        .map((t) => ({ ...t, ...patch }));

      pruneAiSuggestions(
        [...toAssign.filter((id) => idSet.has(id)), ...simFlow.seedIds],
        nextItems,
      );
      void refreshCoverage();

      restoreFilterSnapshot(simFlow.filterSnapshot);
      setSelected(new Set());
      // Stay on current mode; enterOfferRule clears focus
      enterOfferRule(
        simFlow.seedSnapshots,
        simFlow.categoryId,
        accepted,
        excludedTxs,
      );
    } catch (e) {
      alert(e instanceof Error ? e.message : "Group assign failed");
    } finally {
      setBulkBusy(false);
    }
  }

  async function onOverride(txId: string, categoryId: string) {
    if (!categoryId) return;
    // During similar review, row category changes shouldn't restart the flow
    if (simFlow.phase === "reviewing_similar") {
      setSavingId(txId);
      try {
        const prev = items.find((t) => t.id === txId);
        if (prev) pushUndo(`Assigned category`, [prev]);
        await api.overrideCategory(categoryId, txId);
        const forceInternal = categoryImpliesInternal(categoryId);
        const patch = {
          category_id: categoryId,
          category_override: true as const,
          ...(forceInternal ? { is_internal_transfer: true } : {}),
        };
        const nextItems = items.map((t) =>
          t.id === txId ? { ...t, ...patch } : t,
        );
        setItems(nextItems);
        pruneAiSuggestions([txId], nextItems);
        void refreshCoverage();
      } catch (e) {
        alert(e instanceof Error ? e.message : "Override failed");
      } finally {
        setSavingId(null);
      }
      return;
    }

    setSavingId(txId);
    try {
      const prev = items.find((t) => t.id === txId);
      if (prev) {
        const catName = catMap.get(categoryId)?.name || "category";
        pushUndo(`Assigned ${catName}`, [prev]);
      }
      await api.overrideCategory(categoryId, txId);
      const forceInternal = categoryImpliesInternal(categoryId);
      const tx = items.find((t) => t.id === txId);
      const patch = {
        category_id: categoryId,
        category_override: true as const,
        ...(forceInternal ? { is_internal_transfer: true } : {}),
      };
      const nextItems = items.map((t) =>
        t.id === txId ? { ...t, ...patch } : t,
      );
      setItems(nextItems);
      pruneAiSuggestions([txId], nextItems);
      void refreshCoverage();
      if (tx) {
        startGuidedAfterAssign([{ ...tx, ...patch }], categoryId);
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "Override failed");
    } finally {
      setSavingId(null);
    }
  }

  async function applyBulkCategory() {
    if (!bulkCategoryId || selected.size === 0) return;
    // If already in similar review, the dedicated CTA handles group assign
    if (simFlow.phase === "reviewing_similar") {
      await onAssignSimilarSelected();
      return;
    }
    setBulkBusy(true);
    try {
      const ids = [...selected];
      const previousTxs = items.filter((t) => ids.includes(t.id));
      const catName = catMap.get(bulkCategoryId)?.name || "category";
      pushUndo(`Assigned ${catName} to ${ids.length}`, previousTxs);

      const r = await api.bulkOverrideCategory(bulkCategoryId, ids);
      const idSet = new Set(r.transaction_ids);
      const forceInternal = categoryImpliesInternal(bulkCategoryId);
      const patch = {
        category_id: bulkCategoryId,
        category_override: true as const,
        ...(forceInternal ? { is_internal_transfer: true } : {}),
      };
      const nextItems = items.map((t) =>
        idSet.has(t.id) ? { ...t, ...patch } : t,
      );
      setItems(nextItems);
      const affected = previousTxs
        .filter((t) => idSet.has(t.id))
        .map((t) => ({ ...t, ...patch }));
      setSelected(new Set());
      pruneAiSuggestions(
        affected.map((t) => t.id),
        nextItems,
      );
      void refreshCoverage();
      if (affected.length) {
        startGuidedAfterAssign(affected, bulkCategoryId);
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "Bulk assign failed");
    } finally {
      setBulkBusy(false);
    }
  }

  async function saveRule(alsoApply: "none" | "blanks" | "all_matching" = "none") {
    if (!ruleDraft || !ruleDraft.match_value.trim() || !ruleDraft.category_id) return;
    setRuleBusy(true);
    setRuleMsg(null);
    const assignedIds = [...simFlow.seedIds, ...simFlow.acceptedSimilarIds];
    const finishMode = mode;
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
      let loadedItems: Transaction[] | undefined;
      if (alsoApply === "blanks") {
        const applied = await api.applyRules();
        applyNote = ` · filled ${applied.filled} blank tx(s) only`;
        loadedItems = await load({ quiet: true });
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
        loadedItems = await load({ quiet: true });
      } else {
        loadedItems = await load({ quiet: true });
      }
      const itemsForPrune = loadedItems ?? items;
      setRuleMsg(`Rule saved${applyNote}.`);
      setTimeout(() => {
        setRuleDraft(null);
        setRuleMsg(null);
        setSimFlow(IDLE_SIM);
        setFocusIds(null);
        const removed = pruneAiSuggestions(assignedIds, itemsForPrune);
        if (finishMode === "ai") {
          void fetchAiSuggestions({
            excludeKeys: [...aiSkippedKeys, ...aiAppliedKeys, ...removed],
          });
        }
      }, 1800);
    } catch (e) {
      setRuleMsg(e instanceof Error ? e.message : "Could not save rule");
    } finally {
      setRuleBusy(false);
    }
  }

  function dismissRuleOffer() {
    const assignedIds = [...simFlow.seedIds, ...simFlow.acceptedSimilarIds];
    setRuleDraft(null);
    setRuleMsg(null);
    setSimFlow(IDLE_SIM);
    setFocusIds(null);
    setSelected(new Set());
    const removed = pruneAiSuggestions(assignedIds, items);
    if (mode === "ai") {
      void fetchAiSuggestions({
        excludeKeys: [...aiSkippedKeys, ...aiAppliedKeys, ...removed],
      });
    }
  }

  // Recompute plain-English + warning when advanced match fields change
  useEffect(() => {
    if (simFlow.phase !== "offer_rule") return;
    setRuleDraft((d) => {
      if (!d) return d;
      const categoryName = catMap.get(d.category_id)?.name || "category";
      const excluded = items.filter((t) => simFlow.excludedIds.includes(t.id));
      const analysis = analyseRuleAgainstEvidence(
        {
          match_field: d.match_field as RuleSuggestion["match_field"],
          match_type: d.match_type as RuleSuggestion["match_type"],
          match_value: d.match_value,
          institution_scope: d.institution_scope || null,
        },
        categoryName,
        d.seedTxs,
        excluded,
      );
      if (
        analysis.plainEnglish === d.plainEnglish &&
        analysis.warning === d.warning
      ) {
        return d;
      }
      return {
        ...d,
        plainEnglish: analysis.plainEnglish,
        warning: analysis.warning,
      };
    });
  }, [
    // Intentionally keyed on match fields only (functional update reads latest draft)
    ruleDraft?.match_field,
    ruleDraft?.match_type,
    ruleDraft?.match_value,
    ruleDraft?.institution_scope,
    ruleDraft?.category_id,
    simFlow.phase,
    simFlow.excludedIds,
    items,
    catMap,
  ]);

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

  async function fetchAiSuggestions(opts?: {
    excludeKeys?: string[];
    merchant_key?: string;
    hint?: string;
  }) {
    setToolsBusy("ai");
    setAiMsg(null);
    try {
      const exclude =
        opts?.excludeKeys ?? [...aiSkippedKeys, ...aiAppliedKeys];
      const r = await api.aiCategorizeSuggest({
        limit: 12,
        exclude_merchant_keys: exclude,
        merchant_key: opts?.merchant_key,
        hint: opts?.hint,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      if (opts?.merchant_key) {
        // Re-suggest single merchant: replace or prepend that suggestion
        const next = r.suggestions || [];
        setAiSuggestions((prev) => {
          const without = prev.filter((s) => s.merchant_key !== opts.merchant_key);
          return [...next, ...without];
        });
      } else {
        setAiSuggestions(r.suggestions || []);
      }
      if (!r.configured) {
        setAiMsg(
          r.message ||
            "Grok not configured — set AI_ENABLED=true and XAI_API_KEY on the server.",
        );
      } else if (r.message && !(r.suggestions || []).length) {
        setAiMsg(r.message);
      } else {
        const engine = r.model === "sandbox-heuristic" ? "Demo AI" : "Grok";
        setAiMsg(
          `${engine} · ${r.merchants_suggested}/${r.merchants_considered} merchants` +
            (r.tokens_used ? ` · ~${r.tokens_used} tokens` : "") +
            ` · quota ${r.quota_used}/${r.quota_cap}`,
        );
      }
    } catch (e) {
      setAiMsg(e instanceof Error ? e.message : "AI suggest failed");
    } finally {
      setToolsBusy(null);
    }
  }

  function skipAiSuggestion(s: AiCategorySuggestion) {
    setAiSkippedKeys((prev) =>
      prev.includes(s.merchant_key) ? prev : [...prev, s.merchant_key],
    );
    setAiSuggestions((prev) => {
      const rest = prev.filter((x) => x.merchant_key !== s.merchant_key);
      return [...rest, s];
    });
  }

  function showAiTransactions(s: AiCategorySuggestion) {
    // Focus only — do not force uncategorized filter or leave AI mode
    setQ(s.label);
    setFocusIds(s.transaction_ids.length ? s.transaction_ids : null);
    window.setTimeout(() => {
      txTableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);
  }

  /**
   * AI Review & apply: open guided similar-review with the cluster pre-selected.
   * Nothing is written until the user confirms group assign (can uncheck false positives).
   * Stays in AI mode; workbench embeds below the queue.
   */
  function reviewAndApplyAi(s: AiCategorySuggestion) {
    const needsPick = Boolean(s.needs_human) || !s.category_id;
    const categoryId = needsPick
      ? aiCategoryPicks[s.merchant_key] || ""
      : s.category_id;
    if (!categoryId) {
      setAiMsg("Pick a category before Review & apply.");
      return;
    }
    if (!s.transaction_ids.length) {
      setAiMsg("No transactions on this suggestion.");
      return;
    }

    const ids = s.transaction_ids;
    const inPage = items.filter((t) => ids.includes(t.id));
    // Prefer loaded rows; if none in page, still focus by id (table may be empty until full ledger)
    const similarIds = inPage.length > 0 ? inPage.map((t) => t.id) : ids;

    setAiSuggestions((prev) =>
      prev.filter((x) => x.merchant_key !== s.merchant_key),
    );
    setAiMsg(
      `Review ${similarIds.length} “${s.label}” transaction(s) · uncheck any that don’t fit, then assign.`,
    );

    const snapshot: FilterSnapshot = {
      search: searchParams.toString(),
      q,
    };
    setRuleDraft(null);
    setRuleMsg(null);
    setFocusIds(similarIds);
    setSelected(new Set(similarIds));
    setSimFlow({
      phase: "reviewing_similar",
      categoryId,
      seedIds: [],
      seedSnapshots: [],
      similarIds,
      excludedIds: [],
      acceptedSimilarIds: [],
      filterSnapshot: snapshot,
    });
    window.setTimeout(() => {
      txTableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);
  }

  function openGroupFocus(ids: string[]) {
    if (!ids.length) return;
    // Stay on Groups mode — workbench embeds when focusIds is set
    setFocusIds(ids);
    setSelected(new Set(ids));
    window.setTimeout(() => {
      txTableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);
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

  const guidedCategoryName =
    (simFlow.categoryId && catMap.get(simFlow.categoryId)?.name) ||
    (ruleDraft && catMap.get(ruleDraft.category_id)?.name) ||
    "category";

  const similarSelectedCount = useMemo(() => {
    if (simFlow.phase !== "reviewing_similar") return 0;
    const seedSet = new Set(simFlow.seedIds);
    return [...selected].filter((id) => !seedSet.has(id)).length;
  }, [simFlow.phase, simFlow.seedIds, selected]);

  /** Review always; Groups/AI embed table when focused or mid guided flow. */
  const showWorkbench =
    mode === "review" ||
    ((mode === "groups" || mode === "ai") &&
      (Boolean(focusIds?.length) || simFlow.phase !== "idle"));

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
            Review transactions, assign categories, find similar rows, and save rules
            {someSelected ? ` · ${selected.size} selected` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {hasActiveScope && (
            <button type="button" className="btn-ghost text-sm" onClick={clearScope}>
              <X className="h-4 w-4" /> Clear filters
            </button>
          )}
          {focusIds && focusIds.length > 0 && simFlow.phase !== "reviewing_similar" && (
            <button
              type="button"
              className="btn-ghost text-sm"
              onClick={() => {
                setFocusIds(null);
                setSelected(new Set());
              }}
            >
              Clear focus ({focusIds.length})
            </button>
          )}
        </div>
      </div>

      {/* Mode segmented control */}
      <div
        className="inline-flex flex-wrap rounded-xl border border-white/10 bg-white/[0.03] p-1"
        role="tablist"
        aria-label="Categorize mode"
      >
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            role="tab"
            aria-selected={mode === m.id}
            className={cn(
              "rounded-lg px-3.5 py-1.5 text-sm font-medium transition",
              mode === m.id
                ? "bg-brand/20 text-brand shadow-sm"
                : "text-ink-muted hover:text-ink",
            )}
            onClick={() => setWorkspaceMode(m.id)}
          >
            {m.label}
            {m.id === "rules" ? ` (${rules.length})` : ""}
          </button>
        ))}
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

      {useLatestBatch && mode === "review" && (
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
      {showAllLedger && mode === "review" && (
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

      {/* Coverage + tools (Review mode) */}
      {mode === "review" && (
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
              <p className="mt-0.5 text-[10px] text-ink-faint">
                Expense coverage (income assigns do not change this).
              </p>
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
            <div className="flex flex-col gap-2">
              <div>
                <button
                  type="button"
                  className="btn-secondary text-xs"
                  disabled={!!toolsBusy || isReadOnly}
                  title={
                    isReadOnly
                      ? "Read-only demo"
                      : "Create common starter rules from your categories, then optionally fill blanks"
                  }
                  onClick={() =>
                    void runTool("scan", async () => {
                      const r: BootstrapRulesResult = await api.bootstrapRules(true);
                      const a = r.apply as { filled?: number } | undefined;
                      return (
                        `Installed +${r.rules_created} starter rules` +
                        (a?.filled != null ? ` · filled ${a.filled} blanks` : "")
                      );
                    })
                  }
                >
                  {toolsBusy === "scan" ? "Working…" : "Install starter rules"}
                </button>
                <p className="mt-0.5 text-[10px] text-ink-faint">
                  One-time pack of common merchant rules for your categories.
                </p>
              </div>
              <div>
                <button
                  type="button"
                  className="btn-secondary text-xs"
                  disabled={!!toolsBusy || isReadOnly}
                  title={
                    isReadOnly
                      ? "Read-only demo"
                      : "Apply your saved rules to blank and Other residual transactions"
                  }
                  onClick={() =>
                    void runTool("apply", async () => {
                      const r: ApplyRulesResult = await api.applyRules();
                      return `Filled ${r.filled} blanks · unmatched ${r.unmatched}`;
                    })
                  }
                >
                  {toolsBusy === "apply"
                    ? "Working…"
                    : "Apply my rules (blanks & Other)"}
                </button>
                <p className="mt-0.5 text-[10px] text-ink-faint">
                  Other is residual and will be reclassified when rules match —
                  never overwrites manual overrides.
                </p>
              </div>
            </div>
            {toolsMsg && <p className="text-xs text-ink-muted">{toolsMsg}</p>}
          </div>
        </div>
      )}

      {/* Groups mode */}
      {mode === "groups" && (
        <div className="card space-y-4 p-4">
          <div className="flex items-start gap-2">
            <span className="rounded-lg bg-brand/15 p-2 text-brand">
              <Layers className="h-4 w-4" />
            </span>
            <div>
              <h2 className="font-semibold">Smart groups</h2>
              <p className="text-sm text-ink-muted">
                Triage clusters from the loaded ledger. Click a group or cluster to review
                those transactions.
              </p>
            </div>
          </div>
          {smartGroups.length === 0 ? (
            <p className="text-sm text-ink-muted">
              No groups for the current load — widen scope or import more statements.
            </p>
          ) : (
            <ul className="space-y-3">
              {smartGroups.map((g) => (
                <li
                  key={g.id}
                  className="rounded-xl border border-white/10 bg-white/[0.02] p-3"
                >
                  <button
                    type="button"
                    className="flex w-full flex-wrap items-center justify-between gap-2 text-left"
                    onClick={() => openGroupFocus(g.transactionIds)}
                  >
                    <div className="min-w-0">
                      <div className="font-medium text-ink">{g.title}</div>
                      <div className="text-xs text-ink-muted">{g.description}</div>
                    </div>
                    <span className="shrink-0 rounded-full bg-brand/15 px-2.5 py-0.5 text-xs font-semibold text-brand">
                      {g.transactionIds.length}
                    </span>
                  </button>
                  {g.clusters.length > 0 && (
                    <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto border-t border-white/5 pt-2">
                      {g.clusters.slice(0, 20).map((c) => (
                        <li key={c.key}>
                          <button
                            type="button"
                            className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-white/5"
                            onClick={() => openGroupFocus(c.transactionIds)}
                          >
                            <span className="truncate text-ink-muted">
                              {c.label}
                              {c.hint ? (
                                <span className="text-ink-faint"> · {c.hint}</span>
                              ) : null}
                            </span>
                            <span className="shrink-0 text-ink-faint">
                              {c.transactionIds.length}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* AI assist mode */}
      {mode === "ai" && (
        <div className="card space-y-4 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-start gap-2">
              <span className="rounded-lg bg-brand/15 p-2 text-brand">
                <Sparkles className="h-4 w-4" />
              </span>
              <div>
                <h2 className="font-semibold">AI assist</h2>
                <p className="text-sm text-ink-muted">
                  Suggest categories for uncategorized merchants. You review and apply —
                  nothing is saved until you confirm.
                  {isSandboxDemo ? " Sandbox may use local demo heuristics." : ""}
                </p>
                {(dateFrom || dateTo) && (
                  <p className="mt-1 text-xs text-brand">
                    Suggestions limited to {dateFrom || "…"} → {dateTo || "…"}
                  </p>
                )}
              </div>
            </div>
            <button
              type="button"
              className="btn-primary text-sm inline-flex items-center gap-1.5"
              disabled={!!toolsBusy || isReadOnly}
              title={
                isReadOnly
                  ? "Read-only demo — AI suggest is disabled"
                  : "Fetch next batch of merchant suggestions"
              }
              onClick={() => void fetchAiSuggestions()}
            >
              <Sparkles className="h-3.5 w-3.5" />
              {toolsBusy === "ai" ? "Suggesting…" : "Suggest next batch"}
            </button>
          </div>
          {aiMsg && <p className="text-xs text-ink-muted">{aiMsg}</p>}
          {aiSuggestions.length === 0 ? (
            <p className="text-sm text-ink-faint">
              No suggestions yet. Click “Suggest next batch” to scan uncategorized
              merchants.
            </p>
          ) : (
            <ul className="space-y-3">
              {aiSuggestions.map((s) => {
                const needsPick = Boolean(s.needs_human) || !s.category_id;
                const pick = aiCategoryPicks[s.merchant_key] || "";
                const hint = aiHints[s.merchant_key] || "";
                return (
                  <li
                    key={s.merchant_key}
                    className="rounded-xl border border-white/10 bg-white/[0.02] p-3"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-ink">{s.label}</span>
                          {s.needs_human && (
                            <span className="rounded-full bg-warn/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warn">
                              Needs human
                            </span>
                          )}
                        </div>
                        <div className="mt-0.5 text-xs text-ink-muted">
                          {needsPick ? (
                            <span className="text-warn">Pick a category below</span>
                          ) : (
                            <>
                              → {s.category_name}{" "}
                              <span className="text-ink-faint">
                                · {(s.confidence * 100).toFixed(0)}% · {s.sample_count}{" "}
                                tx
                              </span>
                            </>
                          )}
                          {s.reason ? (
                            <span className="text-ink-faint"> · {s.reason}</span>
                          ) : null}
                        </div>
                      </div>
                      <div className="text-[11px] text-ink-faint">
                        {s.transaction_ids.length} tx in cluster
                      </div>
                    </div>

                    {needsPick && (
                      <label className="mt-2 block text-xs text-ink-faint">
                        Category
                        <select
                          className="input mt-1 max-w-xs py-1.5 text-sm"
                          value={pick}
                          onChange={(e) =>
                            setAiCategoryPicks((prev) => ({
                              ...prev,
                              [s.merchant_key]: e.target.value,
                            }))
                          }
                        >
                          <option value="">Choose…</option>
                          {catsSorted.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}

                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        className="btn-primary text-[11px]"
                        disabled={isReadOnly || (needsPick && !pick)}
                        onClick={() => reviewAndApplyAi(s)}
                      >
                        Review &amp; apply
                      </button>
                      <button
                        type="button"
                        className="btn-secondary text-[11px]"
                        onClick={() => skipAiSuggestion(s)}
                      >
                        Skip for later
                      </button>
                      <button
                        type="button"
                        className="btn-ghost text-[11px]"
                        onClick={() => showAiTransactions(s)}
                      >
                        Show transactions
                      </button>
                    </div>

                    <div className="mt-2 flex flex-wrap items-end gap-2">
                      <label className="min-w-[12rem] flex-1 text-[11px] text-ink-faint">
                        Hint for re-suggest
                        <input
                          className="input mt-0.5 py-1.5 text-xs"
                          placeholder="e.g. grocery store in Prague"
                          value={hint}
                          onChange={(e) =>
                            setAiHints((prev) => ({
                              ...prev,
                              [s.merchant_key]: e.target.value,
                            }))
                          }
                        />
                      </label>
                      <button
                        type="button"
                        className="btn-ghost text-[11px]"
                        disabled={!!toolsBusy || isReadOnly || !hint.trim()}
                        onClick={() =>
                          void fetchAiSuggestions({
                            merchant_key: s.merchant_key,
                            hint: hint.trim(),
                          })
                        }
                      >
                        Re-suggest with hint
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      {/* Rules mode */}
      {mode === "rules" && (
        <div className="card space-y-4 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-start gap-2">
              <span className="rounded-lg bg-brand/15 p-2 text-brand">
                <Tags className="h-4 w-4" />
              </span>
              <div>
                <h2 className="font-semibold">Category rules</h2>
                <p className="text-sm text-ink-muted">
                  Saved match patterns that auto-fill categories on import and when you
                  apply rules. Other is residual and will be reclassified when rules
                  match.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={!!toolsBusy || isReadOnly}
                onClick={() =>
                  void runTool("scan", async () => {
                    const r: BootstrapRulesResult = await api.bootstrapRules(true);
                    const a = r.apply as { filled?: number } | undefined;
                    return (
                      `Installed +${r.rules_created} starter rules` +
                      (a?.filled != null ? ` · filled ${a.filled} blanks` : "")
                    );
                  })
                }
              >
                {toolsBusy === "scan" ? "Working…" : "Install starter rules"}
              </button>
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={!!toolsBusy || isReadOnly}
                title="Apply your saved rules to blank and Other residual transactions"
                onClick={() =>
                  void runTool("apply", async () => {
                    const r: ApplyRulesResult = await api.applyRules();
                    return `Filled ${r.filled} blanks · unmatched ${r.unmatched}`;
                  })
                }
              >
                {toolsBusy === "apply"
                  ? "Working…"
                  : "Apply my rules (blanks & Other)"}
              </button>
            </div>
          </div>
          {toolsMsg && <p className="text-xs text-ink-muted">{toolsMsg}</p>}
          <RulesTable
            rules={rules}
            catMap={catMap}
            catsSorted={catsSorted}
            editingRuleId={editingRuleId}
            editRuleDraft={editRuleDraft}
            setEditingRuleId={setEditingRuleId}
            setEditRuleDraft={setEditRuleDraft}
            ruleActionBusy={ruleActionBusy}
            setRuleActionBusy={setRuleActionBusy}
            load={load}
            setToolsMsg={setToolsMsg}
            isReadOnly={isReadOnly}
          />
        </div>
      )}

      {/* Guided flow cards (visible across modes when active) */}
      {simFlow.phase === "offer_similar" && (
        <div className="card space-y-3 border-brand/25 p-4">
          <div className="flex items-start gap-2">
            <span className="rounded-lg bg-brand/15 p-2 text-brand">
              <Sparkles className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="font-semibold">Look for other transactions like this?</h2>
              <p className="text-sm text-ink-muted">
                You assigned{" "}
                <span className="font-medium text-ink">{guidedCategoryName}</span>
                {simFlow.seedSnapshots[0]
                  ? ` to ${vendorDisplayName(simFlow.seedSnapshots[0])}`
                  : ""}
                . We can find similar rows (same merchant, same money direction) for you
                to review before applying.
              </p>
            </div>
            <button
              type="button"
              className="btn-ghost p-2"
              aria-label="Dismiss"
              onClick={onOfferSimilarNo}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              onClick={onOfferSimilarYes}
            >
              Yes
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={onOfferSimilarNo}
            >
              No, just this
            </button>
          </div>
        </div>
      )}

      {simFlow.phase === "reviewing_similar" && (
        <div className="sticky top-14 z-30 card space-y-3 border-brand/40 bg-slate-950/95 p-4 shadow-lg backdrop-blur-md">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="font-semibold text-brand">Reviewing similar transactions</h2>
              <p className="text-sm text-ink-muted">
                Table is filtered to the seed plus similar candidates. Uncheck false
                positives, then assign{" "}
                <span className="font-medium text-ink">{guidedCategoryName}</span> to
                the selected rows.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={bulkBusy || isReadOnly}
              onClick={() => void onAssignSimilarSelected()}
            >
              {bulkBusy ? <Spinner className="h-4 w-4 border-t-slate-900" /> : null}
              Assign {guidedCategoryName} to {similarSelectedCount} selected
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={bulkBusy}
              onClick={onCancelSimilarReview}
            >
              Cancel review
            </button>
          </div>
        </div>
      )}

      {simFlow.phase === "offer_rule" && ruleDraft && (
        <div className="card space-y-3 border-brand/25 p-4">
          <div className="flex items-start gap-2">
            <span className="rounded-lg bg-brand/15 p-2 text-brand">
              <Tags className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="font-semibold">Save a rule for next time?</h2>
              <p className="mt-1 text-sm text-ink">
                {ruleDraft.plainEnglish}
              </p>
              {ruleDraft.warning && (
                <p className="mt-2 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
                  {ruleDraft.warning}
                </p>
              )}
              <p className="mt-1 text-xs text-ink-faint">
                Preview on loaded list: would match{" "}
                <span className="font-semibold text-ink">{rulePreviewCount}</span>{" "}
                non-override transaction(s).
              </p>
            </div>
            <button
              type="button"
              className="btn-ghost p-2"
              aria-label="Dismiss"
              onClick={dismissRuleOffer}
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {ruleMsg && <p className="text-sm text-brand">{ruleMsg}</p>}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={ruleBusy || !ruleDraft.match_value.trim() || isReadOnly}
              onClick={() => void saveRule("none")}
            >
              {ruleBusy ? <Spinner className="h-4 w-4 border-t-slate-900" /> : null}
              Save rule
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={ruleBusy}
              onClick={dismissRuleOffer}
            >
              Don&apos;t save
            </button>
          </div>

          <button
            type="button"
            className="flex items-center gap-1 text-xs text-ink-faint hover:text-ink-muted"
            onClick={() => setRuleAdvancedOpen((v) => !v)}
          >
            {ruleAdvancedOpen ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
            Advanced match options
          </button>

          {ruleAdvancedOpen && (
            <div className="space-y-3 rounded-lg border border-white/10 bg-white/[0.03] p-3">
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
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn-secondary text-xs"
                  disabled={ruleBusy || !ruleDraft.match_value.trim() || isReadOnly}
                  onClick={() => void saveRule("blanks")}
                >
                  Save rule &amp; fill blanks only
                </button>
                <button
                  type="button"
                  className="btn-ghost text-xs"
                  disabled={ruleBusy || !ruleDraft.match_value.trim() || isReadOnly}
                  onClick={() => void saveRule("all_matching")}
                >
                  Save rule &amp; reclassify all matching
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Filters + table (review always; groups/ai when focused or guided) */}
      {showWorkbench && (
        <>
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
                {filtered.length} txs · assign a category · find similar · save a rule
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
                  disabled={simFlow.phase === "reviewing_similar"}
                />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Filter className="h-4 w-4 text-ink-faint" />
                <select
                  className="input w-auto py-2"
                  value={currency}
                  disabled={simFlow.phase === "reviewing_similar"}
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
                  disabled={simFlow.phase === "reviewing_similar"}
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
                  disabled={simFlow.phase === "reviewing_similar"}
                  onChange={(e) => patchParams({ date_from: e.target.value || null })}
                />
              </label>
              <label className="text-xs text-ink-faint">
                To
                <input
                  type="date"
                  className="input mt-1 w-auto py-2"
                  value={dateTo}
                  disabled={simFlow.phase === "reviewing_similar"}
                  onChange={(e) => patchParams({ date_to: e.target.value || null })}
                />
              </label>
              <label className="flex items-center gap-2 pb-2 text-sm text-ink-muted">
                <input
                  type="checkbox"
                  checked={hideTransfers}
                  disabled={simFlow.phase === "reviewing_similar"}
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
                  disabled={simFlow.phase === "reviewing_similar"}
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
                disabled={simFlow.phase === "reviewing_similar"}
                onClick={selectUncategorizedInView}
              >
                Select uncategorized in view
              </button>
            </div>
          </div>

          {/* Bulk action bar */}
          {someSelected && simFlow.phase !== "reviewing_similar" && (
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
                disabled={!bulkCategoryId || bulkBusy || isReadOnly}
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

          <div ref={txTableRef} className="scroll-mt-28 text-xs text-ink-faint">
            {filtered.length} shown
            {total !== filtered.length ? ` · ${total} from server` : ""}
            {hasActiveScope ? " · filtered" : ""}
            {simFlow.phase === "reviewing_similar" ? " · similar review" : ""}
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              title="No transactions match these filters"
              description={
                simFlow.phase === "offer_similar" || simFlow.phase === "offer_rule"
                  ? "Rows may have left this filter after assign — continue with the guided steps above."
                  : "Clear filters or widen the date range."
              }
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
                      const isSeed =
                        simFlow.phase === "reviewing_similar" &&
                        simFlow.seedIds.includes(t.id);
                      return (
                        <tr
                          key={t.id}
                          className={cn(
                            "hover:bg-white/[0.02]",
                            isSel && "bg-brand/5",
                            isSeed && "bg-brand/10",
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
                              {isSeed && (
                                <span className="badge bg-brand/20 text-brand">Seed</span>
                              )}
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
                              <div className="truncate text-xs text-ink-faint">
                                {t.description}
                              </div>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <select
                                className="input max-w-[11rem] py-1.5 text-xs"
                                value={t.category_id || ""}
                                disabled={savingId === t.id || isReadOnly}
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
        </>
      )}

      {/* Undo toast */}
      {undoVisible && undoEntry && (
        <div className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-xl border border-white/15 bg-slate-950/95 px-4 py-3 shadow-2xl backdrop-blur-md">
          <span className="text-sm text-ink">{undoEntry.label}</span>
          <button
            type="button"
            className="btn-secondary inline-flex items-center gap-1.5 text-xs"
            disabled={undoBusy || isReadOnly}
            onClick={() => void performUndo()}
          >
            <Undo2 className="h-3.5 w-3.5" />
            {undoBusy ? "Undoing…" : "Undo"}
          </button>
          <button
            type="button"
            className="btn-ghost p-1.5"
            aria-label="Dismiss undo"
            onClick={() => setUndoEntry(null)}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}

type RulesTableProps = {
  rules: CategoryRule[];
  catMap: Map<string, Category>;
  catsSorted: Category[];
  editingRuleId: string | null;
  editRuleDraft: {
    match_field: string;
    match_type: string;
    match_value: string;
    category_id: string;
    priority: number;
    is_active: boolean;
  } | null;
  setEditingRuleId: (id: string | null) => void;
  setEditRuleDraft: Dispatch<
    SetStateAction<{
      match_field: string;
      match_type: string;
      match_value: string;
      category_id: string;
      priority: number;
      is_active: boolean;
    } | null>
  >;
  ruleActionBusy: string | null;
  setRuleActionBusy: (id: string | null) => void;
  load: (opts?: { quiet?: boolean }) => Promise<Transaction[] | undefined>;
  setToolsMsg: (msg: string | null) => void;
  isReadOnly: boolean;
};

function RulesTable({
  rules,
  catMap,
  catsSorted,
  editingRuleId,
  editRuleDraft,
  setEditingRuleId,
  setEditRuleDraft,
  ruleActionBusy,
  setRuleActionBusy,
  load,
  setToolsMsg,
  isReadOnly,
}: RulesTableProps) {
  if (rules.length === 0) {
    return (
      <p className="text-sm text-ink-muted">
        No rules yet. Install starter rules or save one after assigning a category.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-white/5">
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
                          <option value="counterparty_name">counterparty_name</option>
                          <option value="source_institution">source_institution</option>
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
                          disabled={ruleActionBusy === r.id || isReadOnly}
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
                      {catMap.get(r.category_id)?.name || r.category_id.slice(0, 8)}
                    </td>
                    <td className="px-4 py-2">{r.is_active ? "Yes" : "No"}</td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        <button
                          type="button"
                          className="btn-secondary px-2 py-0.5 text-[11px]"
                          disabled={isReadOnly}
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
                          disabled={ruleActionBusy === r.id || isReadOnly}
                          onClick={() => {
                            if (
                              !window.confirm(`Deactivate rule “${r.match_value}”?`)
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
  );
}
