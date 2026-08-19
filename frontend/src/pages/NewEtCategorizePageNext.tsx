import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "react-router-dom";
import { Sparkles, Undo2, X } from "lucide-react";
import { api } from "../api/client";
import type {
  Category,
  CategoryCoverage,
  CategoryRule,
  Transaction,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { CATEGORIZE_DESK } from "../auth/labDesk";
import { EmptyState, PageLoader, Spinner } from "../components/Spinner";
import { CategoriesModeNext } from "../features/categorize-next/CategoriesModeNext";
import { CoverageLine } from "../features/categorize-next/CoverageLine";
import { GrokPlusPanelNext } from "../features/categorize-next/GrokPlusPanelNext";
import {
  NextStepsCardNext,
  ReviewSimilarCardNext,
} from "../features/categorize-next/GuidedCardsNext";
import { ReviewFilterChips } from "../features/categorize-next/ReviewFilterChips";
import { ReviewWorkbench } from "../features/categorize-next/ReviewWorkbench";
import { RulesModeNext } from "../features/categorize-next/RulesModeNext";
import {
  isoDaysAgo,
  isUuid,
  normTxId,
  SORT_DEFAULT_DIR,
  txHasRealCategory,
  txIsExpense,
  txIsIncome,
  txSignedAmount,
  txSortDescription,
  type SortDir,
  type TxSortKey,
} from "../features/categorize-next/txView";
import { CategorizeHub } from "../features/categorize-next/CategorizeHub";
import { VendorInbox, type VendorApplyRow } from "../features/categorize-next/VendorInbox";
import {
  isGrokPlusOverlay,
  MODES,
  modeFromSearchParams,
  screenFromSearchParams,
  workspaceModeParamPatch,
  type WorkspaceMode,
} from "../features/categorize-next/workspaceMode";
import {
  markWizardDone,
  wizardDone,
} from "../features/new-et/CategorizeWizard";
import { useGrokPlus } from "../features/new-et/GrokPlusContext";
import { GrokPlusStatus } from "../features/new-et/GrokPlusStatus";
import { LabNextChrome } from "../lab-chrome/LabNextChrome";
import { estimateGrokPlusLadder, formatUsdEstimate } from "../lib/aiCost";
import {
  createUndoEntry,
  isUndoValid,
  snapshotFromTx,
  type UndoEntry,
} from "../lib/categorizeUndo";
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
} from "../lib/ruleSuggest";

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

/** Lab next Categorize: leftover vendor inbox first. Same ledger mutations as classic. */
export function NewEtCategorizePageNext() {
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
  const [vendorApplyKey, setVendorApplyKey] = useState<string | null>(null);
  const loadGen = useRef(0);
  const txTableRef = useRef<HTMLDivElement | null>(null);
  const [setupBanner, setSetupBanner] = useState(() => !wizardDone());
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
  const lifeDomainParam = searchParams.get("life_domain") || "";
  const filterFlag = searchParams.get("filter") || "";
  const unconvertedOnly = searchParams.get("unconverted") === "1";
  const grokPlusOpen = isGrokPlusOverlay(searchParams);
  const screen = screenFromSearchParams(searchParams);
  const mode: WorkspaceMode = modeFromSearchParams(searchParams);

  useEffect(() => {
    setQ(qFromUrl);
  }, [qFromUrl]);

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
    patchParams(workspaceModeParamPatch(next));
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

    if (lifeDomainParam) {
      const want = lifeDomainParam.toLowerCase();
      rows = rows.filter((t) => {
        const cat = t.category_id ? catMap.get(t.category_id) : undefined;
        return (cat?.life_domain || "").toLowerCase() === want;
      });
    }
    if (filterFlag === "fixed") {
      rows = rows.filter((t) => {
        const cat = t.category_id ? catMap.get(t.category_id) : undefined;
        return (cat?.necessity || "") === "Fixed";
      });
    }
    if (filterFlag === "transfer_leak") {
      rows = rows.filter((t) => {
        if (!txIsExpense(t) || txHasRealCategory(t, catMap)) return false;
        const blob = `${t.merchant || ""} ${t.description || ""} ${t.original_description || ""}`.toLowerCase();
        return /transfer|przelew|převod|own.?account|internal/.test(blob);
      });
    }
    if (unconvertedOnly) {
      rows = rows.filter((t) => t.amount_usd == null || t.amount_usd === "");
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
    incomeOnly,
    lifeDomainParam,
    filterFlag,
    unconvertedOnly,
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

  const hasActiveScope = Boolean(
    dateFrom ||
      dateTo ||
      categoryIdParam ||
      multiCategoryIds.length ||
      expensesOnly ||
      incomeOnly ||
      q.trim() ||
      currency ||
      lifeDomainParam ||
      filterFlag ||
      unconvertedOnly ||
      searchParams.get("hide_transfers") === "1",
  );

  function clearScope() {
    setSearchParams({}, { replace: true });
    setQ("");
    setFocusIds(null);
    setSimFlow(IDLE_SIM);
    setRuleDraft(null);
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
      const recategorized =
        Boolean(prev?.category_override) ||
        Boolean(prev && !isResidualCategory(prev, catMap));
      const patch = {
        category_id: categoryId,
        category_override: recategorized,
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
      setItems((cur) =>
        cur.map((t) => {
          if (!idSet.has(t.id)) return t;
          const recategorized =
            t.category_override || !isResidualCategory(t, catMap);
          return {
            ...t,
            category_id: bulkCategoryId,
            category_override: recategorized,
            ...(forceInternal ? { is_internal_transfer: true } : {}),
          };
        }),
      );
      const seeds = items
        .filter((t) => idSet.has(t.id))
        .map((t) => ({
          ...t,
          category_id: bulkCategoryId,
          category_override:
            t.category_override || !isResidualCategory(t, catMap),
          ...(forceInternal ? { is_internal_transfer: true } : {}),
        }));
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
    const next = working.map((t) => {
      if (!idSet.has(t.id)) return t;
      const recategorized =
        t.category_override || !isResidualCategory(t, catMap);
      return {
        ...t,
        category_id: categoryId,
        category_override: recategorized,
        ...(forceInternal ? { is_internal_transfer: true } : {}),
      };
    });
    const seeds = next.filter((t) => idSet.has(t.id));
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
      if (grokPlusOpen) grokPlus.consumeKeys([bucket.key]);
      if (opts?.makeRule && seeds.length) {
        await createVendorRule(seeds, categoryId);
        void load({ quiet: true });
      } else if (seeds.length) {
        startGuidedAfterAssign(seeds, categoryId);
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
      if (grokPlusOpen) grokPlus.consumeKeys(keys);
      void refreshCoverage();
      if (makeRule) void load({ quiet: true });
    } catch (e) {
      alert(e instanceof Error ? e.message : "Apply all failed");
    } finally {
      setVendorApplyKey(null);
      setBulkBusy(false);
      setApplyProgress(null);
    }
  }

  function startGrokPlus() {
    patchParams({ panel: "grokplus", mode: null });
    if (grokPlus.phase !== "running") grokPlus.start(catsSorted);
  }

  function onWipe() {
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
        patchParams({ panel: null });
        return load();
      })
      .catch((e) => alert(e instanceof Error ? e.message : "Wipe failed"))
      .finally(() => setWipeBusy(false));
  }

  const categorySelectValue =
    multiCategoryIds.length > 0 ? "__multi__" : categoryIdParam || "";

  const grokChipLabel =
    grokPlus.phase === "running"
      ? "Working — matching leftovers"
      : grokPlus.phase === "paused" && grokPlus.buckets.length
        ? "Ask Grok+ — ready for review"
        : grokPlus.phase === "caught_up"
          ? "Ask Grok+ — ready for review"
          : "Ask Grok+";

  const usdPer = grokPlus.lastBatchCostUsd || 0.01;
  const ladder = estimateGrokPlusLadder({
    categorized: ledgerCoverage.categorized,
    uncategorized: ledgerCoverage.uncategorized,
    leftoverVendors: vendorBuckets.length,
    usdPerLeftoverBatch: usdPer,
  });
  const ladderText = ladder.length
    ? `Est. leftover $ ${ladder.map((r) => `${r.pct}% ~${formatUsdEstimate(r.estUsd)}`).join(" · ")}`
    : null;

  const residualTxCount = vendorBuckets.reduce((n, b) => n + b.count, 0);
  const grokPlusSupporting =
    grokPlus.phase === "running"
      ? "Working — matching leftovers"
      : (grokPlus.phase === "paused" || grokPlus.phase === "caught_up") &&
          grokPlus.buckets.length
        ? "Ready for review"
        : "Suggest only";
  const ledgerTxTotal = coverage?.tx_total ?? ledgerCoverage.total;

  return (
    <LabNextChrome config={CATEGORIZE_DESK} label="Categorize desk">
      {loading && items.length === 0 ? (
        <PageLoader label="Loading categorize workspace…" />
      ) : error && items.length === 0 ? (
        <EmptyState
          title="Couldn’t load workspace"
          description={error}
          action={
            <button type="button" className="btn-primary" onClick={() => void load()}>
              Retry
            </button>
          }
        />
      ) : (
        <div className="min-w-0 max-w-full space-y-4">
          {screen === "hub" ? (
            <CategorizeHub
              leftoverCount={ledgerCoverage.uncategorized}
              categorizedCount={ledgerCoverage.categorized}
              ledgerTxTotal={ledgerTxTotal}
              itemsLength={items.length}
              total={total}
              leftoverVendorCount={vendorBuckets.length}
              residualTxCount={residualTxCount}
              rulesCount={rules.length}
              categoriesCount={cats.length}
              coveragePct={coverage != null ? coverage.coverage_pct : null}
              coverageStatus={coverage?.status}
              progressNote={coverage?.progress_note}
              ladderText={ladderText}
              grokPlusSupporting={grokPlusSupporting}
              showSetupBanner={setupBanner}
              onSkipSetup={() => {
                markWizardDone();
                setSetupBanner(false);
              }}
              onAskGrokPlus={() => {
                if (grokPlus.phase !== "running") grokPlus.start(catsSorted);
              }}
              isReadOnly={isReadOnly}
              wipeBusy={wipeBusy}
              onWipe={onWipe}
            />
          ) : (
            <>
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

          {mode === "review" ? (
            <>
              <VendorInbox
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
                onOpen={(b) => void openVendorBucket(b)}
                onCategoryCreated={(cat) => setCats((prev) => [...prev, cat])}
                applyProgress={applyProgress}
              />

              <CoverageLine
                pct={ledgerCoverage.pct}
                categorized={ledgerCoverage.categorized}
                uncategorized={ledgerCoverage.uncategorized}
                itemsLength={items.length}
                total={total}
                ladderText={ladderText}
              >
                <button
                  type="button"
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
                    grokPlusOpen || grokPlus.phase === "running"
                      ? "border-brand/40 bg-brand/10 text-brand"
                      : "border-white/10 text-ink-muted hover:border-brand/40 hover:text-ink",
                  )}
                  onClick={() => startGrokPlus()}
                >
                  {grokPlus.phase === "running" ? (
                    <Spinner className="h-3.5 w-3.5 border-t-brand" />
                  ) : (
                    <Sparkles className="h-3.5 w-3.5" />
                  )}
                  {grokChipLabel}
                </button>
              </CoverageLine>

              {grokPlus.started && !grokPlusOpen ? (
                <GrokPlusStatus variant="float" />
              ) : null}

              {grokPlusOpen ? (
                <GrokPlusPanelNext
                  buckets={grokPlus.buckets}
                  catsSorted={catsSorted}
                  busy={
                    bulkBusy ||
                    ruleBusy ||
                    (grokPlus.phase === "running" && grokPlus.buckets.length === 0)
                  }
                  isReadOnly={isReadOnly}
                  applyingKey={vendorApplyKey}
                  message={grokPlus.phase === "running" ? null : grokPlus.message}
                  onApply={(b, categoryId) => void applyVendorBucket(b, categoryId)}
                  onApplyRule={(b, categoryId) =>
                    void applyVendorBucket(b, categoryId, { makeRule: true })
                  }
                  onApplyAll={(rows, makeRule) => void applyVendorBatch(rows, makeRule)}
                  onOpen={(b) => void openVendorBucket(b)}
                  onClose={() => patchParams({ panel: null })}
                  onCategoryCreated={(cat) => setCats((prev) => [...prev, cat])}
                  coachNote={
                    grokPlus.coachNote ||
                    (grokPlus.runCount <= 1
                      ? "Drill into a category, click a vendor, and add a category if something important is missing before you approve."
                      : null)
                  }
                  applyProgress={applyProgress}
                />
              ) : null}

              {simFlow.phase === "next_steps" ? (
                <NextStepsCardNext
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
              ) : null}
              {simFlow.phase === "reviewing_similar" ? (
                <ReviewSimilarCardNext
                  categoryName={catMap.get(simFlow.categoryId)?.name || "category"}
                  selectedCount={[...selected].filter((id) => !simFlow.seedIds.includes(id)).length}
                  busy={bulkBusy}
                  isReadOnly={isReadOnly}
                  onAssign={() => void onAssignSimilarSelected()}
                  onCancel={() => {
                    enterNextSteps(simFlow.seedSnapshots, simFlow.categoryId, [], []);
                  }}
                />
              ) : null}

              <ReviewFilterChips
                q={q}
                onQChange={setQ}
                dateFrom={dateFrom}
                dateTo={dateTo}
                onDateFrom={(v) => patchParams({ date_from: v || null })}
                onDateTo={(v) => patchParams({ date_to: v || null })}
                currency={currency}
                onCurrency={(v) => patchParams({ currency: v || null })}
                categorySelectValue={categorySelectValue}
                catsSorted={catsSorted}
                multiCategoryCount={multiCategoryIds.length}
                onCategory={(v) => {
                  if (v === "" || v === "__multi__") {
                    patchParams({ category_id: null, category_ids: null });
                  } else if (v === "uncategorized") {
                    patchParams({ category_id: "uncategorized", category_ids: null });
                  } else {
                    patchParams({ category_id: v, category_ids: null });
                  }
                }}
                hideTransfers={hideTransfers}
                onHideTransfers={(next) =>
                  patchParams({ hide_transfers: next ? "1" : "0" })
                }
                expensesOnly={expensesOnly}
                onExpensesOnly={(next) =>
                  patchParams({
                    expenses_only: next ? "1" : null,
                    income_only: next ? null : searchParams.get("income_only"),
                  })
                }
                incomeOnly={incomeOnly}
                onIncomeOnly={(next) =>
                  patchParams({
                    income_only: next ? "1" : null,
                    expenses_only: next ? null : searchParams.get("expenses_only"),
                  })
                }
                lifeDomain={lifeDomainParam}
                filterFlag={filterFlag}
                unconvertedOnly={unconvertedOnly}
                onClearParam={(key) => patchParams({ [key]: null })}
                onShortcutUncat30={() => {
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
                onShortcutExp30={() => {
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
                onShortcutUncatAll={() => {
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
                onWipe={onWipe}
                wipeBusy={wipeBusy}
                isReadOnly={isReadOnly}
                hasActiveScope={hasActiveScope}
                onClearScope={clearScope}
                focusCount={
                  focusIds && simFlow.phase !== "reviewing_similar" ? focusIds.length : 0
                }
                onClearFocus={() => {
                  setFocusIds(null);
                  setSelected(new Set());
                }}
                onSelectUncategorized={selectUncategorizedInView}
              />

              <ReviewWorkbench
                tableRef={txTableRef}
                filteredCount={filtered.length}
                total={total}
                hasActiveScope={hasActiveScope}
                sortedRows={sortedRows}
                selected={selected}
                allFilteredSelected={allFilteredSelected}
                someSelected={someSelected}
                sortKey={sortKey}
                sortDir={sortDir}
                onToggleSort={toggleSort}
                catMap={catMap}
                catsSorted={catsSorted}
                savingId={savingId}
                isReadOnly={isReadOnly}
                onToggleOne={toggleOne}
                onToggleAll={toggleAllFiltered}
                onOverride={(id, categoryId) => void onOverride(id, categoryId)}
                onClearCategory={(id) => void onClearCategory(id)}
                bulkCategoryId={bulkCategoryId}
                onBulkCategoryId={setBulkCategoryId}
                bulkBusy={bulkBusy}
                onApplyBulk={() => void applyBulkCategory()}
                onClearSelected={() => void onClearSelectedCategories()}
                onClearSelection={() => setSelected(new Set())}
              />
            </>
          ) : null}

          {mode === "rules" ? (
            <RulesModeNext
              rules={rules}
              catsSorted={catsSorted}
              catMap={catMap}
              isReadOnly={isReadOnly}
              onChanged={() => load({ quiet: true })}
            />
          ) : null}

          {mode === "categories" ? (
            <CategoriesModeNext
              cats={cats}
              isReadOnly={isReadOnly}
              onChanged={() => load({ quiet: true })}
            />
          ) : null}
            </>
          )}

          {undoVisible && undoEntry ? (
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
          ) : null}
        </div>
      )}
    </LabNextChrome>
  );
}
