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
import { api } from "../api/client";
import type {
  AiClusterSuggestion,
  AiStatus,
  Category,
  CategoryCoverage,
  CategoryRule,
  Transaction,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Money } from "../components/Money";
import { EmptyState, PageLoader, Spinner } from "../components/Spinner";
import { AiDesk } from "../features/new-et/AiDesk";
import { CategoriesMode } from "../features/new-et/CategoriesMode";
import {
  OfferRuleCard,
  OfferSimilarCard,
  ReviewSimilarCard,
} from "../features/new-et/GuidedCards";
import { RulesMode } from "../features/new-et/RulesMode";
import {
  createUndoEntry,
  isUndoValid,
  snapshotFromTx,
  type UndoEntry,
} from "../lib/categorizeUndo";
import { formatUsd } from "../lib/money";
import { cn } from "../lib/cn";
import {
  analyseRuleAgainstEvidence,
  refineMatchValueFromEvidence,
} from "../lib/ruleExplain";
import {
  countRuleMatches,
  findSimilarTransactions,
  suggestRuleFromTransactions,
  vendorDisplayName,
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
type SimPhase = "idle" | "offer_similar" | "reviewing_similar" | "offer_rule";

type SimFlow = {
  phase: SimPhase;
  categoryId: string;
  seedIds: string[];
  seedSnapshots: Transaction[];
  similarIds: string[];
  acceptedSimilarIds: string[];
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
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [aiStatusError, setAiStatusError] = useState<string | null>(null);
  const [aiClusters, setAiClusters] = useState<AiClusterSuggestion[]>([]);
  const [aiMsg, setAiMsg] = useState<string | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiPicks, setAiPicks] = useState<Record<string, string>>({});
  const loadGen = useRef(0);
  const txTableRef = useRef<HTMLDivElement | null>(null);

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
    let cancelled = false;
    void (async () => {
      try {
        const s = await api.aiStatus();
        if (!cancelled) setAiStatus(s);
      } catch (e) {
        if (!cancelled) {
          setAiStatusError(e instanceof Error ? e.message : "Could not load AI status");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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

  const filtered = useMemo(() => {
    let rows = items;

    if (focusIds && focusIds.length > 0) {
      const allow = new Set(focusIds);
      return rows.filter((t) => allow.has(t.id));
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
    setRuleDraft(null);
    setSimFlow({
      phase: "offer_similar",
      categoryId,
      seedIds: seeds.map((t) => t.id),
      seedSnapshots: seeds,
      similarIds: [],
      acceptedSimilarIds: [],
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

  function enterOfferRule(
    seeds: Transaction[],
    categoryId: string,
    accepted: Transaction[] = [],
    excluded: Transaction[] = [],
  ) {
    setRuleDraft(buildRuleDraft([...seeds, ...accepted], excluded, categoryId));
    setFocusIds(null);
    setSimFlow({
      phase: "offer_rule",
      categoryId,
      seedIds: seeds.map((t) => t.id),
      seedSnapshots: seeds,
      similarIds: [],
      acceptedSimilarIds: accepted.map((t) => t.id),
    });
  }

  function onOfferSimilarYes() {
    const seeds = simFlow.seedSnapshots;
    if (!seeds.length) return;
    const similar = findSimilarTransactions(items, seeds, {
      sameAmountSign: true,
      residualOnly: true,
      catMap,
      sortAlpha: true,
    });
    if (similar.length === 0) {
      enterOfferRule(seeds, simFlow.categoryId, [], []);
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

  async function onAssignSimilarSelected() {
    if (!simFlow.categoryId) return;
    const seedIdSet = new Set(simFlow.seedIds);
    const toAssign = [...selected].filter((id) => !seedIdSet.has(id));
    const excluded = simFlow.similarIds.filter((id) => !selected.has(id));
    const excludedTxs = items.filter((t) => excluded.includes(t.id));
    if (toAssign.length === 0) {
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
      const nextItems = items.map((t) => (idSet.has(t.id) ? { ...t, ...patch } : t));
      setItems(nextItems);
      const accepted = previousTxs
        .filter((t) => idSet.has(t.id))
        .map((t) => ({ ...t, ...patch }));
      void refreshCoverage();
      setSelected(new Set());
      enterOfferRule(simFlow.seedSnapshots, simFlow.categoryId, accepted, excludedTxs);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Group assign failed");
    } finally {
      setBulkBusy(false);
    }
  }

  async function saveOfferedRule() {
    if (!ruleDraft || !ruleDraft.match_value.trim() || !ruleDraft.category_id) return;
    setRuleBusy(true);
    try {
      await api.createCategoryRule({
        priority: 100,
        match_field: ruleDraft.match_field,
        match_type: ruleDraft.match_type,
        match_value: ruleDraft.match_value.trim(),
        category_id: ruleDraft.category_id,
        set_internal_transfer: categoryImpliesInternal(ruleDraft.category_id),
        institution_scope: ruleDraft.institution_scope.trim() || undefined,
        is_active: true,
        notes: "Created from New ET guided flow",
      });
      setRuleDraft(null);
      setSimFlow(IDLE_SIM);
      await load({ quiet: true });
    } catch (e) {
      alert(e instanceof Error ? e.message : "Save rule failed");
    } finally {
      setRuleBusy(false);
    }
  }

  async function fetchAiClusters() {
    setAiBusy(true);
    setAiMsg(null);
    try {
      const r = await api.aiCategorizeClusters({
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        exclude_transaction_ids: aiClusters.flatMap((c) => c.transaction_ids),
      });
      setAiStatus((prev) =>
        prev
          ? { ...prev, configured: r.configured, enabled: r.enabled, model: r.model, quota_used: r.quota_used, quota_cap: r.quota_cap }
          : prev,
      );
      if (!r.configured) {
        setAiClusters([]);
        setAiMsg(r.message || "AI is not configured.");
        return;
      }
      setAiClusters(r.clusters);
      setAiMsg(r.message || null);
    } catch (e) {
      setAiMsg(e instanceof Error ? e.message : "Cluster request failed");
    } finally {
      setAiBusy(false);
    }
  }

  function focusCluster(c: AiClusterSuggestion) {
    setFocusIds(c.transaction_ids);
    setSelected(new Set(c.transaction_ids));
    window.setTimeout(() => {
      txTableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
  }

  async function applyCluster(c: AiClusterSuggestion) {
    const categoryId =
      c.needs_human || !c.category_id ? aiPicks[c.cluster_key] || "" : c.category_id;
    if (!categoryId) return;
    const ids = c.transaction_ids.filter((id) => items.some((t) => t.id === id));
    if (!ids.length) return;
    setBulkBusy(true);
    try {
      const previousTxs = items.filter((t) => ids.includes(t.id));
      const catName = catMap.get(categoryId)?.name || c.category_name || "category";
      pushUndo(`Assigned ${catName} to ${ids.length}`, previousTxs);
      const forceInternal =
        c.kind === "internal_transfer" || categoryImpliesInternal(categoryId);
      const r = await api.bulkOverrideCategory(categoryId, ids);
      const idSet = new Set(r.transaction_ids);
      const patch = {
        category_id: categoryId,
        category_override: true as const,
        ...(forceInternal ? { is_internal_transfer: true } : {}),
      };
      const nextItems = items.map((t) => (idSet.has(t.id) ? { ...t, ...patch } : t));
      setItems(nextItems);
      const seeds = previousTxs
        .filter((t) => idSet.has(t.id))
        .map((t) => ({ ...t, ...patch }));
      setAiClusters((prev) => prev.filter((x) => x.cluster_key !== c.cluster_key));
      setSelected(new Set());
      setFocusIds(null);
      void refreshCoverage();
      if (seeds.length) startGuidedAfterAssign(seeds, categoryId);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Apply cluster failed");
    } finally {
      setBulkBusy(false);
    }
  }

  async function refreshCoverage() {
    try {
      const cov = await api.categoryCoverage(180);
      setCoverage(cov);
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
      void refreshCoverage();
      if (seeds.length) startGuidedAfterAssign(seeds, bulkCategoryId);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Bulk assign failed");
    } finally {
      setBulkBusy(false);
    }
  }

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
                        patchParams({
                          q: m.label,
                          category_id: "uncategorized",
                          category_ids: null,
                        });
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
            </div>
          </div>
        </div>
      )}

      {mode === "review" && (
        <>
          <AiDesk
            status={aiStatus}
            statusError={aiStatusError}
            clusters={aiClusters}
            message={aiMsg}
            busy={aiBusy}
            isReadOnly={isReadOnly}
            catsSorted={catsSorted}
            categoryPicks={aiPicks}
            onSuggest={() => void fetchAiClusters()}
            onFocus={focusCluster}
            onApply={(c) => void applyCluster(c)}
            onSkip={(c) =>
              setAiClusters((prev) => prev.filter((x) => x.cluster_key !== c.cluster_key))
            }
            onPick={(key, categoryId) =>
              setAiPicks((prev) => ({ ...prev, [key]: categoryId }))
            }
          />
          {simFlow.phase === "offer_similar" && (
            <OfferSimilarCard
              categoryName={catMap.get(simFlow.categoryId)?.name || "category"}
              vendorLabel={
                simFlow.seedSnapshots[0]
                  ? vendorDisplayName(simFlow.seedSnapshots[0])
                  : ""
              }
              onYes={onOfferSimilarYes}
              onNo={() =>
                enterOfferRule(simFlow.seedSnapshots, simFlow.categoryId, [], [])
              }
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
                setSelected(new Set());
                enterOfferRule(simFlow.seedSnapshots, simFlow.categoryId, [], []);
              }}
            />
          )}
          {simFlow.phase === "offer_rule" && ruleDraft && (
            <OfferRuleCard
              plainEnglish={ruleDraft.plainEnglish}
              warning={ruleDraft.warning}
              previewCount={countRuleMatches(items, {
                match_field: ruleDraft.match_field,
                match_type: ruleDraft.match_type,
                match_value: ruleDraft.match_value,
                institution_scope: ruleDraft.institution_scope || null,
                onlyWithoutOverride: true,
              })}
              busy={ruleBusy}
              isReadOnly={isReadOnly}
              canSave={Boolean(ruleDraft.match_value.trim())}
              onSave={() => void saveOfferedRule()}
              onDismiss={() => {
                setRuleDraft(null);
                setSimFlow(IDLE_SIM);
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

          <div ref={txTableRef} className="scroll-mt-28 text-xs text-ink-faint">
            {filtered.length} shown
            {total !== filtered.length ? ` · ${total} from server` : ""}
            {hasActiveScope ? " · filtered" : ""}
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
