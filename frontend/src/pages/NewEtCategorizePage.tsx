import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowLeftRight,
  ChevronDown,
  ChevronUp,
  Filter,
  Search,
  Undo2,
  X,
} from "lucide-react";
import { ApiError, api } from "../api/client";
import type {
  Category,
  CategoryCoverage,
  CategoryRule,
  Transaction,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Money } from "../components/Money";
import { EmptyState, PageLoader, Spinner } from "../components/Spinner";
import { CategoriesMode } from "../features/new-et/CategoriesMode";
import {
  NextStepsCard,
  ReviewSimilarCard,
} from "../features/new-et/GuidedCards";
import { RulesMode } from "../features/new-et/RulesMode";
import { GrokPlusPanel } from "../features/new-et/GrokPlusPanel";
import { useGrokPlus } from "../features/new-et/GrokPlusContext";
import {
  CategorizeWizard,
  wizardDone,
} from "../features/new-et/CategorizeWizard";
import { VendorRollup, type VendorApplyRow } from "../features/new-et/VendorRollup";
import {
  createUndoEntry,
  isUndoValid,
  snapshotFromTx,
  type UndoEntry,
} from "../lib/categorizeUndo";
import { estimateGrokPlusLadder, formatUsdEstimate } from "../lib/aiCost";
import { cn } from "../lib/cn";
import {
  analyseRuleAgainstEvidence,
  refineMatchValueFromEvidence,
} from "../lib/ruleExplain";
import {
  countRuleMatches,
  findSimilarTransactions,
  groupTransactionsByVendor,
  isResidualCategory,
  ledgerCategoryCounts,
  suggestRuleFromTransactions,
  vendorDisplayName,
  type VendorBucket,
} from "../lib/ruleSuggest";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const MODES = [
  { id: "review", label: "Review" },
  { id: "rules", label: "Rules" },
  { id: "categories", label: "Categories" },
] as const;

type WorkspaceMode = (typeof MODES)[number]["id"];
type TxSortKey = "date" | "description" | "category" | "source" | "amount";
type SortDir = "asc" | "desc";
type SimPhase = "idle" | "next_steps" | "reviewing_similar";

type SimFlow = {
  phase: SimPhase;
  categoryId: string;
  seedIds: string[];
  seedSnapshots: Transaction[];
  similarIds: string[];
  acceptedSimilarIds: string[];
  excludedIds: string[];
};

type RuleDraft = {
  match_field: string;
  match_type: string;
  match_value: string;
  category_id: string;
  institution_scope: string;
  seedTxs: Transaction[];
  excludedTxs: Transaction[];
  plainEnglish: string;
  warning: string | null;
};

const IDLE_SIM: SimFlow = {
  phase: "idle",
  categoryId: "",
  seedIds: [],
  seedSnapshots: [],
  similarIds: [],
  acceptedSimilarIds: [],
  excludedIds: [],
};

const SORT_DEFAULT_DIR: Record<TxSortKey, SortDir> = {
  date: "desc",
  description: "asc",
  category: "asc",
  source: "asc",
  amount: "desc",
};

function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

function normTxId(id: string): string {
  return id.trim().toLowerCase();
}

function txSignedAmount(t: Transaction): number {
  const raw =
    t.amount_usd != null && t.amount_usd !== "" ? t.amount_usd : t.amount;
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

function txIsExpense(t: Transaction): boolean {
  return txSignedAmount(t) < 0;
}

function txIsIncome(t: Transaction): boolean {
  return txSignedAmount(t) > 0;
}

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

function txSortDescription(t: Transaction): string {
  return (t.merchant || t.description || "").trim();
}

function modeFromSearchParams(params: URLSearchParams): WorkspaceMode {
  const m = params.get("mode");
  if (m === "rules" || m === "categories" || m === "review") return m;
  if (params.get("panel") === "rules") return "rules";
  return "review";
}

function isoDaysAgo(days: number): { from: string; to: string } {
  const to = new Date();
  const from = new Date();
  from.setDate(to.getDate() - days);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { from: iso(from), to: iso(to) };
}

export function NewEtCategorizePage() {
  const { isReadOnly } = useAuth();
  const grokPlus = useGrokPlus();
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [cats, setCats] = useState<Category[]>([]);
  const [coverage, setCoverage] = useState<CategoryCoverage | null>(null);
  const [countAdj, setCountAdj] = useState({ cat: 0, uncat: 0 });
  const [rules, setRules] = useState<CategoryRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkCategoryId, setBulkCategoryId] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [mode, setMode] = useState<WorkspaceMode>(() =>
    modeFromSearchParams(searchParams),
  );
  const [sortKey, setSortKey] = useState<TxSortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [q, setQ] = useState(searchParams.get("q") || "");
  const [focusIds, setFocusIds] = useState<string[] | null>(null);
  const [simFlow, setSimFlow] = useState<SimFlow>(IDLE_SIM);
  const [ruleDraft, setRuleDraft] = useState<RuleDraft | null>(null);
  const [ruleBusy, setRuleBusy] = useState(false);
  const [undoEntry, setUndoEntry] = useState<UndoEntry | null>(null);
  const [undoBusy, setUndoBusy] = useState(false);
  const [undoTick, setUndoTick] = useState(0);
  const [vendorPanel, setVendorPanel] = useState<
    "off" | "plain" | "grok" | "grokplus"
  >("off");
  const [vendorApplyKey, setVendorApplyKey] = useState<string | null>(null);
  const [grokBusy, setGrokBusy] = useState(false);
  const [grokMsg, setGrokMsg] = useState<string | null>(null);
  const [grokDebug, setGrokDebug] = useState<string | null>(null);
  const [grokBuckets, setGrokBuckets] = useState<VendorBucket[]>([]);
  const loadGen = useRef(0);
  const txTableRef = useRef<HTMLDivElement | null>(null);
  const grokExcludeRef = useRef<string[]>([]);
  const [showWizard, setShowWizard] = useState(() => !wizardDone());
  const [applyProgress, setApplyProgress] = useState<{
    current: number;
    total: number;
  } | null>(null);
  const [wipeBusy, setWipeBusy] = useState(false);

  const dateFrom = searchParams.get("date_from") || "";
  const dateTo = searchParams.get("date_to") || "";
  const currency = searchParams.get("currency") || "";
  const hideTransfers = searchParams.get("hide_transfers") !== "0";
  const expensesOnly = searchParams.get("expenses_only") === "1";
  const incomeOnly = searchParams.get("income_only") === "1";
  const categoryIdParam = searchParams.get("category_id") || "";
  const categoryIdsParam = searchParams.get("category_ids") || "";
  const qFromUrl = searchParams.get("q") || "";

  useEffect(() => {
    setQ(qFromUrl);
  }, [qFromUrl]);

  useEffect(() => {
    if (searchParams.get("panel") === "grokplus") {
      setVendorPanel("grokplus");
      setMode("review");
    }
  }, [searchParams]);

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
    patchParams({ mode: next === "review" ? null : next, panel: null });
  }

  const load = useCallback(
    async (opts?: { quiet?: boolean }): Promise<void> => {
      const quiet = opts?.quiet ?? false;
      const gen = ++loadGen.current;
      if (!quiet) setLoading(true);
      if (!quiet) setError(null);
      try {
        const apiCategoryId =
          categoryIdParam && isUuid(categoryIdParam) ? categoryIdParam : undefined;
        const [t, c, cov, r] = await Promise.all([
          api.transactions({
            limit: 3000,
            date_from: dateFrom || undefined,
            date_to: dateTo || undefined,
            currency: currency || undefined,
            is_internal_transfer: hideTransfers ? false : undefined,
            category_id: apiCategoryId,
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
        setCountAdj({ cat: 0, uncat: 0 });
        setRules(r.items);
        setError(null);
      } catch (e) {
        if (gen !== loadGen.current) return;
        if (quiet) return;
        setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        if (gen === loadGen.current && !quiet) setLoading(false);
      }
    },
    [currency, hideTransfers, dateFrom, dateTo, categoryIdParam],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (simFlow.phase === "reviewing_similar") return;
    setSelected(new Set());
  }, [dateFrom, dateTo, currency, hideTransfers, expensesOnly, incomeOnly, categoryIdParam, categoryIdsParam, q, simFlow.phase]);

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

  const catsSorted = useMemo(
    () =>
      cats.slice().sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)),
    [cats],
  );

  const vendorBuckets = useMemo(() => {
    const pool = items.filter((t) => {
      if (!isResidualCategory(t, catMap)) return false;
      if (expensesOnly && !txIsExpense(t)) return false;
      if (incomeOnly && !txIsIncome(t)) return false;
      return true;
    });
    return groupTransactionsByVendor(pool);
  }, [items, catMap, expensesOnly, incomeOnly]);

  const liveCoverage = useMemo(
    () => ledgerCategoryCounts(items, catMap),
    [items, catMap],
  );

  const ledgerCoverage = useMemo(() => {
    const categorized = Math.max(
      0,
      (coverage?.tx_categorized ?? liveCoverage.categorized) + countAdj.cat,
    );
    const uncategorized = Math.max(
      0,
      (coverage?.tx_uncategorized ?? liveCoverage.uncategorized) + countAdj.uncat,
    );
    const all = categorized + uncategorized;
    return {
      categorized,
      uncategorized,
      total: all,
      pct: all > 0 ? (categorized / all) * 100 : 0,
    };
  }, [coverage, liveCoverage, countAdj]);

  const filtered = useMemo(() => {
    let rows = items;

    if (focusIds && focusIds.length > 0) {
      const allow = new Set(focusIds.map(normTxId));
      return rows.filter((t) => allow.has(normTxId(t.id)));
    }

    if (categoryIdParam === "uncategorized") {
      rows = rows.filter((t) => !txHasRealCategory(t, catMap));
    } else if (multiCategoryIds.length > 0) {
      const set = new Set(multiCategoryIds);
      rows = rows.filter((t) => t.category_id != null && set.has(t.category_id));
    } else if (categoryIdParam && isUuid(categoryIdParam)) {
      rows = rows.filter((t) => t.category_id === categoryIdParam);
    }

    if (expensesOnly) rows = rows.filter(txIsExpense);
    if (incomeOnly) rows = rows.filter(txIsIncome);

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
    incomeOnly,
    catMap,
    focusIds,
  ]);

  const sortedRows = useMemo(() => {
    const rows = filtered.slice();
    if (simFlow.phase === "reviewing_similar") {
      rows.sort((a, b) =>
        txSortDescription(a).localeCompare(txSortDescription(b), undefined, {
          sensitivity: "base",
        }),
      );
      return rows;
    }
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
          cmp = txSignedAmount(a) - txSignedAmount(b);
          break;
      }
      if (cmp !== 0) return cmp * dir;
      return a.id.localeCompare(b.id);
    });
    return rows;
  }, [filtered, sortKey, sortDir, catMap, simFlow.phase]);

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
      return `Smaller categories (${multiCategoryIds.length})`;
    }
    if (categoryIdParam === "uncategorized") return "Uncategorized";
    if (categoryIdParam && isUuid(categoryIdParam)) {
      return catMap.get(categoryIdParam)?.name || "Category";
    }
    return null;
  }, [categoryIdParam, multiCategoryIds, catMap]);

  const hasActiveScope = Boolean(
    dateFrom ||
      dateTo ||
      categoryIdParam ||
      multiCategoryIds.length ||
      expensesOnly ||
      incomeOnly ||
      q.trim() ||
      currency ||
      searchParams.get("hide_transfers") === "1",
  );

  const filterChips = useMemo(() => {
    const chips: string[] = [];
    if (dateFrom || dateTo) chips.push(`${dateFrom || "…"} → ${dateTo || "…"}`);
    if (expensesOnly) chips.push("Expenses only");
    if (incomeOnly) chips.push("Income only");
    if (categoryFilterLabel) chips.push(categoryFilterLabel);
    if (currency) chips.push(currency);
    if (q.trim()) chips.push(`Search: “${q.trim()}”`);
    if (hideTransfers) chips.push("Hide internal transfers");
    return chips;
  }, [
    dateFrom,
    dateTo,
    expensesOnly,
    incomeOnly,
    categoryFilterLabel,
    currency,
    q,
    hideTransfers,
  ]);

  function clearScope() {
    setSearchParams({}, { replace: true });
    setQ("");
    setFocusIds(null);
    setSimFlow(IDLE_SIM);
    setRuleDraft(null);
    setMode("review");
  }

  const allFilteredSelected =
    filtered.length > 0 && filtered.every((t) => selected.has(t.id));
  const someSelected = selected.size > 0;

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
    setSelected(
      new Set(
        filtered.filter((t) => !txHasRealCategory(t, catMap)).map((t) => t.id),
      ),
    );
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

  function pushUndo(label: string, previousTxs: Transaction[]) {
    const previous: UndoEntry["previous"] = {};
    if (undoEntry && isUndoValid(undoEntry)) {
      Object.assign(previous, undoEntry.previous);
    }
    for (const t of previousTxs) {
      if (!previous[t.id]) previous[t.id] = snapshotFromTx(t);
    }
    if (Object.keys(previous).length === 0) return;
    setUndoEntry(createUndoEntry(label, previous));
  }

  async function performUndo() {
    if (!undoEntry || !isUndoValid(undoEntry)) {
      setUndoEntry(null);
      return;
    }
    setUndoBusy(true);
    try {
      await api.restoreAssignments(
        Object.entries(undoEntry.previous).map(([id, snap]) => ({
          transaction_id: id,
          category_id: snap.category_id,
          category_override: snap.category_override,
          is_internal_transfer: snap.is_internal_transfer,
        })),
      );
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

  function startGuidedAfterAssign(seeds: Transaction[], categoryId: string) {
    setRuleDraft(buildRuleDraft(seeds, [], categoryId));
    setSimFlow({
      phase: "next_steps",
      categoryId,
      seedIds: seeds.map((t) => t.id),
      seedSnapshots: seeds,
      similarIds: [],
      acceptedSimilarIds: [],
      excludedIds: [],
    });
  }

  function buildRuleDraft(
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
      seedTxs: included,
      excludedTxs: excluded,
      plainEnglish: analysis.plainEnglish,
      warning: analysis.warning,
    };
  }

  function enterNextSteps(
    seeds: Transaction[],
    categoryId: string,
    accepted: Transaction[] = [],
    excluded: Transaction[] = [],
  ) {
    setRuleDraft(buildRuleDraft([...seeds, ...accepted], excluded, categoryId));
    setFocusIds(null);
    setSelected(new Set());
    setSimFlow({
      phase: "next_steps",
      categoryId,
      seedIds: seeds.map((t) => t.id),
      seedSnapshots: seeds,
      similarIds: [],
      acceptedSimilarIds: accepted.map((t) => t.id),
      excludedIds: excluded.map((t) => t.id),
    });
  }

  function similarForSeeds(seeds: Transaction[]): Transaction[] {
    if (!seeds.length) return [];
    const skip = new Set(simFlow.excludedIds);
    return findSimilarTransactions(items, seeds, {
      sameAmountSign: true,
      residualOnly: true,
      catMap,
      sortAlpha: true,
    }).filter((t) => !skip.has(t.id));
  }

  function onReviewSimilar() {
    const seeds = simFlow.seedSnapshots;
    if (!seeds.length) return;
    const similar = similarForSeeds(seeds);
    if (similar.length === 0) {
      enterNextSteps(seeds, simFlow.categoryId, [], []);
      return;
    }
    const seedIds = seeds.map((t) => t.id);
    const similarIds = similar.map((t) => t.id);
    setFocusIds([...seedIds, ...similarIds]);
    setSelected(new Set(similarIds));
    setSimFlow((prev) => ({ ...prev, phase: "reviewing_similar", similarIds }));
    window.setTimeout(() => {
      txTableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
  }

  async function applySimilarIds(
    toAssign: string[],
  ): Promise<Transaction[]> {
    if (!simFlow.categoryId || toAssign.length === 0) return [];
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
    setItems((cur) => cur.map((t) => (idSet.has(t.id) ? { ...t, ...patch } : t)));
    nudgeLedgerCounts(idSet.size);
    void refreshCoverage();
    return previousTxs
      .filter((t) => idSet.has(t.id))
      .map((t) => ({ ...t, ...patch }));
  }

  async function onAssignSimilarSelected() {
    if (!simFlow.categoryId) return;
    const seedIdSet = new Set(simFlow.seedIds);
    const toAssign = [...selected].filter((id) => !seedIdSet.has(id));
    const excluded = simFlow.similarIds.filter((id) => !selected.has(id));
    const excludedTxs = items.filter((t) => excluded.includes(t.id));
    if (toAssign.length === 0) {
      enterNextSteps(simFlow.seedSnapshots, simFlow.categoryId, [], excludedTxs);
      return;
    }
    setBulkBusy(true);
    try {
      const accepted = await applySimilarIds(toAssign);
      enterNextSteps(simFlow.seedSnapshots, simFlow.categoryId, accepted, excludedTxs);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Group assign failed");
    } finally {
      setBulkBusy(false);
    }
  }

  async function onApplyAllSimilar() {
    if (!simFlow.categoryId) return;
    const similar = similarForSeeds(simFlow.seedSnapshots);
    if (similar.length === 0) {
      enterNextSteps(simFlow.seedSnapshots, simFlow.categoryId, [], []);
      return;
    }
    setBulkBusy(true);
    try {
      const accepted = await applySimilarIds(similar.map((t) => t.id));
      enterNextSteps(simFlow.seedSnapshots, simFlow.categoryId, accepted, []);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Apply similar failed");
    } finally {
      setBulkBusy(false);
    }
  }

  async function createVendorRule(seeds: Transaction[], categoryId: string) {
    const draft = buildRuleDraft(seeds, [], categoryId);
    if (!draft.match_value.trim() || !draft.category_id) return;
    await api.createCategoryRule({
      priority: 100,
      match_field: draft.match_field,
      match_type: draft.match_type,
      match_value: draft.match_value.trim(),
      category_id: draft.category_id,
      set_internal_transfer: categoryImpliesInternal(draft.category_id),
      institution_scope: draft.institution_scope.trim() || undefined,
      is_active: true,
      notes: "Created from New ET vendor apply",
    });
  }

  async function persistRule(draft: RuleDraft) {
    if (!draft.match_value.trim() || !draft.category_id) return;
    await api.createCategoryRule({
      priority: 100,
      match_field: draft.match_field,
      match_type: draft.match_type,
      match_value: draft.match_value.trim(),
      category_id: draft.category_id,
      set_internal_transfer: categoryImpliesInternal(draft.category_id),
      institution_scope: draft.institution_scope.trim() || undefined,
      is_active: true,
      notes: "Created from New ET guided flow",
    });
    setRuleDraft(null);
    setSimFlow(IDLE_SIM);
    setFocusIds(null);
    await load({ quiet: true });
  }

  async function saveOfferedRule() {
    if (!ruleDraft) return;
    setRuleBusy(true);
    try {
      await persistRule(ruleDraft);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Save rule failed");
    } finally {
      setRuleBusy(false);
    }
  }

  async function onApplyAndSaveRule() {
    if (!simFlow.categoryId) return;
    const seeds = simFlow.seedSnapshots;
    const similar = similarForSeeds(seeds);
    setRuleBusy(true);
    setBulkBusy(true);
    try {
      const accepted =
        similar.length > 0 ? await applySimilarIds(similar.map((t) => t.id)) : [];
      const draft = buildRuleDraft([...seeds, ...accepted], [], simFlow.categoryId);
      await persistRule(draft);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Apply and save rule failed");
    } finally {
      setRuleBusy(false);
      setBulkBusy(false);
    }
  }

  function nudgeLedgerCounts(assignedResidual: number) {
    if (!assignedResidual) return;
    setCountAdj((prev) => ({
      cat: prev.cat + assignedResidual,
      uncat: prev.uncat - assignedResidual,
    }));
  }

  function nudgeLedgerCleared(clearedCategorized: number) {
    if (!clearedCategorized) return;
    setCountAdj((prev) => ({
      cat: prev.cat - clearedCategorized,
      uncat: prev.uncat + clearedCategorized,
    }));
  }

  async function refreshCoverage() {
    try {
      const cov = await api.categoryCoverage(180);
      setCoverage(cov);
      setCountAdj({ cat: 0, uncat: 0 });
    } catch {
      /* mutation already succeeded */
    }
  }

  async function onClearCategory(txId: string) {
    const prev = items.find((t) => t.id === txId);
    if (!prev) return;
    if (!prev.category_id && !prev.category_override) return;
    setSavingId(txId);
    try {
      pushUndo("Cleared category", [prev]);
      await api.restoreAssignments([
        {
          transaction_id: txId,
          category_id: null,
          category_override: false,
          is_internal_transfer: prev.is_internal_transfer,
        },
      ]);
      setItems((cur) =>
        cur.map((t) =>
          t.id === txId
            ? { ...t, category_id: null, category_override: false }
            : t,
        ),
      );
      if (!isResidualCategory(prev, catMap)) nudgeLedgerCleared(1);
      void refreshCoverage();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Clear category failed");
    } finally {
      setSavingId(null);
    }
  }

  async function onClearSelectedCategories() {
    if (selected.size === 0) return;
    const previousTxs = items.filter(
      (t) => selected.has(t.id) && (t.category_id != null || t.category_override),
    );
    if (!previousTxs.length) return;
    setBulkBusy(true);
    try {
      pushUndo(`Cleared category on ${previousTxs.length}`, previousTxs);
      await api.restoreAssignments(
        previousTxs.map((t) => ({
          transaction_id: t.id,
          category_id: null,
          category_override: false,
          is_internal_transfer: t.is_internal_transfer,
        })),
      );
      const idSet = new Set(previousTxs.map((t) => t.id));
      setItems((prev) =>
        prev.map((t) =>
          idSet.has(t.id)
            ? { ...t, category_id: null, category_override: false }
            : t,
        ),
      );
      nudgeLedgerCleared(
        previousTxs.filter((t) => !isResidualCategory(t, catMap)).length,
      );
      void refreshCoverage();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Clear categories failed");
    } finally {
      setBulkBusy(false);
    }
  }

  async function onOverride(txId: string, categoryId: string) {
    if (!categoryId) {
      await onClearCategory(txId);
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
      const patch = {
        category_id: categoryId,
        category_override: true as const,
        ...(forceInternal ? { is_internal_transfer: true } : {}),
      };
      setItems((cur) => cur.map((t) => (t.id === txId ? { ...t, ...patch } : t)));
      if (prev && isResidualCategory(prev, catMap)) nudgeLedgerCounts(1);
      void refreshCoverage();
      if (simFlow.phase !== "reviewing_similar" && prev) {
        startGuidedAfterAssign([{ ...prev, ...patch }], categoryId);
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "Override failed");
    } finally {
      setSavingId(null);
    }
  }

  async function applyBulkCategory() {
    if (!bulkCategoryId || selected.size === 0) return;
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
      setItems((cur) => cur.map((t) => (idSet.has(t.id) ? { ...t, ...patch } : t)));
      const seeds = previousTxs
        .filter((t) => idSet.has(t.id))
        .map((t) => ({ ...t, ...patch }));
      setSelected(new Set());
      nudgeLedgerCounts(seeds.length);
      void refreshCoverage();
      if (seeds.length) startGuidedAfterAssign(seeds, bulkCategoryId);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Bulk assign failed");
    } finally {
      setBulkBusy(false);
    }
  }

  async function openVendorBucket(bucket: { ids: string[] }) {
    const ids = bucket.ids.map(normTxId).filter(Boolean);
    const have = new Set(items.map((t) => normTxId(t.id)));
    const missing = ids.filter((id) => !have.has(id));
    if (missing.length) {
      try {
        const extra = await api.transactions({
          tx_ids: missing.join(","),
          ids: missing.join(","),
          limit: Math.max(missing.length, 1),
        });
        if (extra.items.length) {
          setItems((prev) => {
            const seen = new Set(prev.map((t) => normTxId(t.id)));
            const next = prev.slice();
            for (const t of extra.items) {
              const key = normTxId(t.id);
              if (!seen.has(key)) {
                next.push(t);
                seen.add(key);
              }
            }
            return next;
          });
        }
      } catch {
        /* still focus rows we already have */
      }
    }
    setFocusIds(ids);
    setSelected(new Set(ids));
    window.setTimeout(() => {
      txTableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
  }

  function markVendorConsumed(keys: string[]) {
    grokExcludeRef.current.push(...keys);
    setGrokBuckets((prev) => prev.filter((b) => !keys.includes(b.key)));
  }

  async function commitVendorAssign(
    working: Transaction[],
    bucket: { key: string; label: string; ids: string[] },
    categoryId: string,
  ): Promise<{ working: Transaction[]; seeds: Transaction[] }> {
    if (!categoryId || bucket.ids.length === 0) {
      return { working, seeds: [] };
    }
    const idSetWant = new Set(bucket.ids);
    const previousTxs = working.filter((t) => idSetWant.has(t.id));
    const catName = catMap.get(categoryId)?.name || "category";
    pushUndo(`Assigned ${catName} to ${previousTxs.length} ${bucket.label}`, previousTxs);
    const r = await api.bulkOverrideCategory(categoryId, bucket.ids);
    const idSet = new Set(r.transaction_ids);
    const forceInternal = categoryImpliesInternal(categoryId);
    const patch = {
      category_id: categoryId,
      category_override: true as const,
      ...(forceInternal ? { is_internal_transfer: true } : {}),
    };
    const next = working.map((t) => (idSet.has(t.id) ? { ...t, ...patch } : t));
    const seeds = previousTxs
      .filter((t) => idSet.has(t.id))
      .map((t) => ({ ...t, ...patch }));
    nudgeLedgerCounts(seeds.length);
    return { working: next, seeds };
  }

  async function applyVendorBucket(
    bucket: { key: string; label: string; ids: string[] },
    categoryId: string,
    opts?: { makeRule?: boolean },
  ) {
    if (!categoryId || bucket.ids.length === 0) return;
    setVendorApplyKey(bucket.key);
    setBulkBusy(true);
    try {
      const { working, seeds } = await commitVendorAssign(items, bucket, categoryId);
      setItems(working);
      void refreshCoverage();
      const left = grokBuckets.filter((b) => b.key !== bucket.key);
      if (vendorPanel === "grokplus") {
        grokPlus.consumeKeys([bucket.key]);
      } else {
        markVendorConsumed([bucket.key]);
      }
      if (vendorPanel === "grok" || vendorPanel === "grokplus") {
        setFocusIds(null);
        setSelected(new Set());
      }
      if (opts?.makeRule && seeds.length) {
        await createVendorRule(seeds, categoryId);
        void load({ quiet: true });
      } else if (seeds.length) {
        startGuidedAfterAssign(seeds, categoryId);
      }
      if (vendorPanel === "grok" && left.length === 0) {
        void fetchGrokVendors();
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "Vendor assign failed");
    } finally {
      setVendorApplyKey(null);
      setBulkBusy(false);
    }
  }

  async function applyVendorBatch(rows: VendorApplyRow[], makeRule: boolean) {
    if (!rows.length) return;
    setBulkBusy(true);
    setApplyProgress({ current: 0, total: rows.length });
    try {
      let working = items;
      for (let i = 0; i < rows.length; i += 1) {
        const row = rows[i];
        setApplyProgress({ current: i + 1, total: rows.length });
        setVendorApplyKey(row.bucket.key);
        const out = await commitVendorAssign(working, row.bucket, row.categoryId);
        working = out.working;
        if (makeRule && out.seeds.length) {
          await createVendorRule(out.seeds, row.categoryId);
        }
      }
      setItems(working);
      setApplyProgress(null);
      const keys = rows.map((r) => r.bucket.key);
      if (vendorPanel === "grokplus") {
        grokPlus.consumeKeys(keys);
      } else {
        markVendorConsumed(keys);
      }
      void refreshCoverage();
      if (makeRule) void load({ quiet: true });
      if (vendorPanel === "grok") {
        setFocusIds(null);
        setSelected(new Set());
        void fetchGrokVendors();
      } else if (vendorPanel === "grokplus") {
        setFocusIds(null);
        setSelected(new Set());
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "Apply all failed");
    } finally {
      setVendorApplyKey(null);
      setBulkBusy(false);
      setApplyProgress(null);
    }
  }

  async function fetchGrokVendors() {
    setVendorPanel("grok");
    setFocusIds(null);
    setSelected(new Set());
    setGrokBusy(true);
    setGrokMsg("Looking up merchants across the full ledger…");
    setGrokDebug(null);
    const preview: VendorBucket[] = [];
    try {
      let r;
      try {
        r = await api.aiVendorSuggest({
          limit: 10,
          exclude_merchant_keys: grokExcludeRef.current,
        });
      } catch (first) {
        if (first instanceof ApiError && first.status === 404) {
          r = await api.aiCategorizeSuggest({
            limit: 10,
            web_search: true,
          });
        } else {
          throw first;
        }
      }
      const sent = r.vendors_sent || [];
      if (sent.length && r.suggestions.length === 0) {
        setGrokBuckets(
          sent.map((v) => ({
            key: v.merchant_key,
            label: v.label,
            count: v.count,
            ids: [],
          })),
        );
      }
      if (!r.configured) {
        setGrokMsg(r.message || "Grok is not configured. Set AI_ENABLED and XAI_API_KEY.");
      } else {
        const previewByKey = new Map(preview.map((b) => [b.key, b]));
        const buckets: VendorBucket[] = r.suggestions.map((s) => {
          const want = (s.category_id || "").trim().toLowerCase();
          const byId = want
            ? catsSorted.find((c) => c.id.toLowerCase() === want)
            : undefined;
          const byName = s.category_name
            ? catsSorted.find(
                (c) =>
                  c.name.toLowerCase() === s.category_name.trim().toLowerCase(),
              )
            : undefined;
          const resolved = byId || byName;
          const prev = previewByKey.get(s.merchant_key);
          return {
            key: s.merchant_key,
            label: s.label,
            count: s.sample_count || s.transaction_ids.length || prev?.count || 0,
            ids: s.transaction_ids.length ? s.transaction_ids : prev?.ids || [],
            suggestedCategoryId: resolved?.id || "",
            suggestedCategoryName: resolved?.name || s.category_name,
            reason: s.reason
              ? `${s.reason}${resolved?.name || s.category_name ? ` → ${resolved?.name || s.category_name}` : ""}`
              : resolved?.name || s.category_name || undefined,
            confidence: s.confidence,
          };
        });
        if (buckets.length) setGrokBuckets(buckets);
        setGrokMsg(
          r.message ||
            (buckets.length
              ? `Grok suggested ${buckets.length} vendor${buckets.length === 1 ? "" : "s"}.`
              : "Grok returned no vendor guesses."),
        );
      }
      const vendorLines = sent
        .map((v, i) => `${i + 1}. ${v.label} ×${v.count} (${v.merchant_key})`)
        .join("\n");
      setGrokDebug(
        [
          vendorLines ? `Vendors sent (${sent.length}):\n${vendorLines}` : "Vendors sent: (none)",
          "",
          "--- system prompt ---",
          r.system_prompt || "(empty)",
          "",
          "--- user prompt ---",
          r.user_prompt || "(empty)",
        ].join("\n"),
      );
    } catch (e) {
      const detail =
        e instanceof ApiError
          ? e.status === 404
            ? "The API running on port 8020 is old — it does not have Ask Grok yet. Restart Start-App, then try again. The merchants below are still ready to Apply."
            : e.message
          : e instanceof Error
            ? e.message
            : "Grok request failed";
      setGrokMsg(detail);
    } finally {
      setGrokBusy(false);
    }
  }

  function startGrokPlus() {
    setVendorPanel("grokplus");
    setFocusIds(null);
    setSelected(new Set());
    if (grokPlus.phase !== "running") grokPlus.start(catsSorted);
  }

  const grokAwaitingClick =
    (vendorPanel === "grok" || vendorPanel === "grokplus") &&
    !(focusIds && focusIds.length);

  const categorySelectValue =
    multiCategoryIds.length > 0
      ? "__multi__"
      : categoryIdParam || "";

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
            Review transactions, assign categories, and manage rules
            {someSelected ? ` · ${selected.size} selected` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
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
          {hasActiveScope && (
            <button type="button" className="btn-ghost text-sm" onClick={clearScope}>
              <X className="h-4 w-4" /> Clear filters
            </button>
          )}
        </div>
      </div>

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
            {m.id === "categories" ? ` (${cats.length})` : ""}
          </button>
        ))}
      </div>

      {showWizard && mode === "review" && (
        <CategorizeWizard
          onOpenVendors={() => setVendorPanel("plain")}
          onOpenCategories={() => setWorkspaceMode("categories")}
          onStartTour={() => startGrokPlus()}
          onSkip={() => setShowWizard(false)}
        />
      )}

      {hasActiveScope && (
        <div className="rounded-xl border border-brand/30 bg-slate-950/95 px-4 py-3">
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

      {mode === "review" && (
        <div className="grid gap-3 lg:grid-cols-3">
          <div className="card p-4 lg:col-span-1">
            <div className="label">Coverage (full ledger)</div>
            <div
              className={cn(
                "text-2xl font-semibold",
                ledgerCoverage.pct >= 90
                  ? "text-ok"
                  : ledgerCoverage.pct >= 70
                    ? "text-warn"
                    : "text-danger",
              )}
            >
              {ledgerCoverage.pct.toFixed(0)}%
            </div>
            <p className="mt-1 text-sm text-ink">
              <span className="font-medium tabular-nums">
                {ledgerCoverage.categorized.toLocaleString()}
              </span>
              <span className="text-ink-muted"> categorized</span>
              <span className="text-ink-faint"> · </span>
              <span className="font-medium tabular-nums">
                {ledgerCoverage.uncategorized.toLocaleString()}
              </span>
              <span className="text-ink-muted"> uncategorized</span>
            </p>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className={cn(
                  "h-full rounded-full",
                  ledgerCoverage.pct >= 90
                    ? "bg-ok"
                    : ledgerCoverage.pct >= 70
                      ? "bg-warn"
                      : "bg-danger",
                )}
                style={{
                  width: `${Math.min(100, Math.max(0, ledgerCoverage.pct))}%`,
                }}
              />
            </div>
            <div className="mt-1 text-[11px] text-ink-faint">
              Full ledger · table shows newest {items.length.toLocaleString()}
              {total > items.length ? ` of ${total.toLocaleString()}` : ""}
              {hideTransfers ? " · internals hidden" : ""}
            </div>
            {(() => {
              const usdPer = grokPlus.lastBatchCostUsd || 0.01;
              const ladder = estimateGrokPlusLadder({
                categorized: ledgerCoverage.categorized,
                uncategorized: ledgerCoverage.uncategorized,
                leftoverVendors: vendorBuckets.length,
                usdPerLeftoverBatch: usdPer,
              });
              return (
                <p className="mt-2 text-[11px] text-ink-faint">
                  Est. Grok+ leftover $ to review{" "}
                  {ladder.map((r) => `${r.pct}% ~${formatUsdEstimate(r.estUsd)}`).join(" · ")}
                  {" "}
                  (estimate · repeat vendors you already assigned skip the model)
                </p>
              );
            })()}
          </div>
          <div className="card p-4 lg:col-span-1">
            <div className="label mb-1">Top uncategorized</div>
            <ul className="max-h-28 space-y-0.5 overflow-y-auto text-xs text-ink-muted">
              {vendorBuckets.slice(0, 6).map((m) => (
                <li key={m.key}>
                  <button
                    type="button"
                    className="flex w-full justify-between gap-2 text-left hover:text-brand"
                    onClick={() => openVendorBucket(m)}
                  >
                    <span className="truncate">{m.label}</span>
                    <span className="shrink-0">×{m.count}</span>
                  </button>
                </li>
              ))}
              {!vendorBuckets.length && (
                <li className="text-ok">None left on this list</li>
              )}
            </ul>
          </div>
          <div className="card flex flex-col justify-center gap-2 p-4 lg:col-span-1">
            <div className="label">Shortcuts</div>
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
                onClick={() => {
                  const { from, to } = isoDaysAgo(29);
                  patchParams({
                    date_from: from,
                    date_to: to,
                    category_id: "uncategorized",
                    category_ids: null,
                    expenses_only: null,
                    income_only: null,
                  });
                }}
              >
                Uncategorized 30d
              </button>
              <button
                type="button"
                className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
                onClick={() => {
                  const { from, to } = isoDaysAgo(29);
                  patchParams({
                    date_from: from,
                    date_to: to,
                    category_id: null,
                    category_ids: null,
                    expenses_only: "1",
                    income_only: null,
                  });
                }}
              >
                Expenses 30d
              </button>
              <button
                type="button"
                className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
                onClick={() => {
                  patchParams({
                    date_from: null,
                    date_to: null,
                    category_id: "uncategorized",
                    category_ids: null,
                    expenses_only: null,
                    income_only: null,
                    q: null,
                  });
                  setQ("");
                }}
              >
                Uncategorized All
              </button>
              <button
                type="button"
                className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
                onClick={() =>
                  setVendorPanel((cur) => (cur === "plain" ? "off" : "plain"))
                }
              >
                By vendor{vendorBuckets.length ? ` (${vendorBuckets.length})` : ""}
              </button>
              <button
                type="button"
                className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
                disabled={grokBusy}
                onClick={() => void fetchGrokVendors()}
              >
                {grokBusy && vendorPanel === "grok" ? "Asking Grok…" : "Ask Grok"}
              </button>
              <button
                type="button"
                className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-ink-muted hover:border-brand/40 hover:text-ink"
                onClick={() => startGrokPlus()}
              >
                {grokPlus.phase === "running" ? "Matching…" : "Ask Grok+"}
              </button>
              <button
                type="button"
                className="rounded-lg border border-danger/30 px-2 py-1 text-[11px] text-danger hover:bg-danger/10"
                disabled={wipeBusy || isReadOnly}
                onClick={() => {
                  if (
                    !window.confirm(
                      "Clear all category assigns and learned vendors? Statements, tags, and internal flags stay.",
                    )
                  ) {
                    return;
                  }
                  setWipeBusy(true);
                  void api
                    .wipeAssignments()
                    .then(() => {
                      grokPlus.dismiss();
                      setGrokBuckets([]);
                      return load();
                    })
                    .catch((e) =>
                      alert(e instanceof Error ? e.message : "Wipe failed"),
                    )
                    .finally(() => setWipeBusy(false));
                }}
              >
                {wipeBusy ? "Wiping…" : "Wipe categorization"}
              </button>
            </div>
          </div>
        </div>
      )}

      {mode === "review" && vendorPanel === "plain" && (
        <VendorRollup
          title="Vendors"
          buckets={vendorBuckets}
          catsSorted={catsSorted}
          busy={bulkBusy || ruleBusy}
          isReadOnly={isReadOnly}
          applyingKey={vendorApplyKey}
          onApply={(b, categoryId) => void applyVendorBucket(b, categoryId)}
          onApplyRule={(b, categoryId) =>
            void applyVendorBucket(b, categoryId, { makeRule: true })
          }
          onApplyAll={(rows, makeRule) => void applyVendorBatch(rows, makeRule)}
          onOpen={openVendorBucket}
          onClose={() => setVendorPanel("off")}
          onCategoryCreated={(cat) => setCats((prev) => [...prev, cat])}
          applyProgress={applyProgress}
        />
      )}

      {mode === "review" && vendorPanel === "grokplus" && (
        <GrokPlusPanel
          buckets={grokPlus.buckets}
          catsSorted={catsSorted}
          busy={
            bulkBusy ||
            ruleBusy ||
            (grokPlus.phase === "running" && grokPlus.buckets.length === 0)
          }
          isReadOnly={isReadOnly}
          applyingKey={vendorApplyKey}
          message={grokPlus.message}
          onApply={(b, categoryId) => void applyVendorBucket(b, categoryId)}
          onApplyRule={(b, categoryId) =>
            void applyVendorBucket(b, categoryId, { makeRule: true })
          }
          onApplyAll={(rows, makeRule) => void applyVendorBatch(rows, makeRule)}
          onOpen={openVendorBucket}
          onExpandCategory={() => {
            setFocusIds(null);
            setSelected(new Set());
          }}
          onClose={() => {
            setVendorPanel("off");
            patchParams({ panel: null });
          }}
          onCategoryCreated={(cat) => setCats((prev) => [...prev, cat])}
          coachNote={
            grokPlus.coachNote ||
            (grokPlus.runCount <= 1
              ? "Drill into a category, click a vendor, and add a category if something important is missing before you approve."
              : null)
          }
          applyProgress={applyProgress}
        />
      )}

      {mode === "review" && vendorPanel === "grok" && (
        <VendorRollup
          title="Grok vendor guesses"
          subtitle={
            grokBusy
              ? "Looking up the top 10 residual vendors…"
              : "Grok looks up each merchant online, then maps it to one of your categories."
          }
          buckets={grokBuckets}
          catsSorted={catsSorted}
          busy={bulkBusy || ruleBusy || grokBusy}
          isReadOnly={isReadOnly}
          applyingKey={vendorApplyKey}
          message={grokMsg}
          debugText={grokDebug}
          onApply={(b, categoryId) => void applyVendorBucket(b, categoryId)}
          onApplyRule={(b, categoryId) =>
            void applyVendorBucket(b, categoryId, { makeRule: true })
          }
          onApplyAll={(rows, makeRule) => void applyVendorBatch(rows, makeRule)}
          onOpen={openVendorBucket}
          onClose={() => setVendorPanel("off")}
          onCategoryCreated={(cat) => setCats((prev) => [...prev, cat])}
        />
      )}

      {mode === "review" && (
        <>
          {simFlow.phase === "next_steps" && (
            <NextStepsCard
              categoryName={catMap.get(simFlow.categoryId)?.name || "category"}
              vendorLabel={
                simFlow.seedSnapshots[0]
                  ? vendorDisplayName(simFlow.seedSnapshots[0])
                  : ""
              }
              similarCount={similarForSeeds(simFlow.seedSnapshots).length}
              rulePreview={ruleDraft?.plainEnglish || ""}
              ruleWarning={ruleDraft?.warning ?? null}
              ruleMatchCount={
                ruleDraft
                  ? countRuleMatches(items, {
                      match_field: ruleDraft.match_field,
                      match_type: ruleDraft.match_type,
                      match_value: ruleDraft.match_value,
                      institution_scope: ruleDraft.institution_scope || null,
                      onlyWithoutOverride: true,
                    })
                  : 0
              }
              busy={bulkBusy || ruleBusy}
              isReadOnly={isReadOnly}
              canSaveRule={Boolean(ruleDraft?.match_value.trim())}
              onReview={onReviewSimilar}
              onApplySimilar={() => void onApplyAllSimilar()}
              onSaveRule={() =>
                void (similarForSeeds(simFlow.seedSnapshots).length > 0
                  ? onApplyAndSaveRule()
                  : saveOfferedRule())
              }
              onDismiss={() => {
                setRuleDraft(null);
                setSimFlow(IDLE_SIM);
                setFocusIds(null);
              }}
            />
          )}
          {simFlow.phase === "reviewing_similar" && (
            <ReviewSimilarCard
              categoryName={catMap.get(simFlow.categoryId)?.name || "category"}
              selectedCount={[...selected].filter((id) => !simFlow.seedIds.includes(id)).length}
              busy={bulkBusy}
              isReadOnly={isReadOnly}
              onAssign={() => void onAssignSimilarSelected()}
              onCancel={() => {
                enterNextSteps(simFlow.seedSnapshots, simFlow.categoryId, [], []);
              }}
            />
          )}
        </>
      )}

      {mode === "rules" && (
        <RulesMode
          rules={rules}
          catsSorted={catsSorted}
          catMap={catMap}
          isReadOnly={isReadOnly}
          onChanged={() => load({ quiet: true })}
        />
      )}

      {mode === "categories" && (
        <CategoriesMode
          cats={cats}
          isReadOnly={isReadOnly}
          onChanged={() => load({ quiet: true })}
        />
      )}

      {mode === "review" && (
        <>
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
                    patchParams({
                      expenses_only: e.target.checked ? "1" : null,
                      income_only: e.target.checked ? null : searchParams.get("income_only"),
                    })
                  }
                  className="rounded border-white/20"
                />
                Expenses only
              </label>
              <label className="flex items-center gap-2 pb-2 text-sm text-ink-muted">
                <input
                  type="checkbox"
                  checked={incomeOnly}
                  onChange={(e) =>
                    patchParams({
                      income_only: e.target.checked ? "1" : null,
                      expenses_only: e.target.checked ? null : searchParams.get("expenses_only"),
                    })
                  }
                  className="rounded border-white/20"
                />
                Income only
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

          {someSelected && (
            <div className="flex flex-col gap-3 rounded-xl border border-brand/30 bg-surface-raised/95 p-3 sm:flex-row sm:items-center">
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
                className="btn-secondary text-sm"
                disabled={bulkBusy || isReadOnly || selected.size === 0}
                onClick={() => void onClearSelectedCategories()}
              >
                Clear category
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

          {grokAwaitingClick ? (
            <p className="text-sm text-ink-faint">
              Click a vendor in the Grok list to see its transactions.
            </p>
          ) : (
          <div ref={txTableRef} className="scroll-mt-28 text-xs text-ink-faint">
            {filtered.length} shown
            {total !== filtered.length ? ` · ${total} from server` : ""}
            {hasActiveScope ? " · filtered" : ""}
          </div>
          )}

          {!grokAwaitingClick && filtered.length === 0 ? (
            <EmptyState
              title="No transactions match these filters"
              description="Clear filters or widen the date range."
            />
          ) : !grokAwaitingClick ? (
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
                          ["date", "Date"],
                          ["description", "Description"],
                          ["category", "Category"],
                          ["source", "Source"],
                          ["amount", "Amount"],
                        ] as Array<[TxSortKey, string]>
                      ).map(([key, label]) => {
                        const active = sortKey === key;
                        return (
                          <th
                            key={key}
                            className={cn(
                              "px-4 py-3",
                              key === "amount" && "text-right",
                            )}
                          >
                            <button
                              type="button"
                              className="inline-flex items-center gap-1 hover:text-ink"
                              onClick={() => toggleSort(key)}
                            >
                              {label}
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
                              <div className="truncate text-xs text-ink-faint">
                                {t.description}
                              </div>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex flex-wrap items-center gap-1.5">
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
                              {(t.category_id || t.category_override) && (
                                <button
                                  type="button"
                                  className="btn-ghost px-1.5 py-1 text-[10px] text-ink-muted"
                                  disabled={savingId === t.id || isReadOnly}
                                  title="Reset to uncategorized"
                                  onClick={() => void onClearCategory(t.id)}
                                >
                                  Reset
                                </button>
                              )}
                              {savingId === t.id && <Spinner className="h-3.5 w-3.5" />}
                            </div>
                            {cat && (
                              <div className="mt-0.5 text-[10px] text-ink-faint">
                                {cat.necessity} · {cat.life_domain}
                              </div>
                            )}
                            {!t.category_id && t.suggest_reason && (
                              <div className="mt-0.5 text-[10px] text-brand/80">
                                Tag: {t.suggest_reason}
                                {t.suggest_category_id
                                  ? ` · ${catMap.get(t.suggest_category_id)?.name || ""}`
                                  : ""}
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
          ) : null}
        </>
      )}

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
