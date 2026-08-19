export const MODES = [
  { id: "review", label: "Review" },
  { id: "rules", label: "Rules" },
  { id: "categories", label: "Categories" },
] as const;

export type WorkspaceMode = (typeof MODES)[number]["id"];

export const WINDOWS = [
  { id: "review", label: "Review leftovers" },
  { id: "grokplus", label: "Ask Grok+" },
  { id: "rules", label: "Rules" },
  { id: "categories", label: "Categories" },
  { id: "txs", label: "Transactions" },
] as const;

export type WindowId = (typeof WINDOWS)[number]["id"];

export type CategorizeScreen =
  | "hub"
  | "review"
  | "grokplus"
  | "rules"
  | "categories"
  | "txs";

const WINDOW_MODES = new Set<string>(["review", "rules", "categories", "txs"]);

export const CATEGORIZE_PATH = "/expenses/categorize";

/** Inbound Spending/Alerts filters, allowlists, and tx= skip the hub. */
export function hasListScope(params: URLSearchParams): boolean {
  return Boolean(
    params.get("date_from") ||
      params.get("date_to") ||
      params.get("currency") ||
      params.get("category_id") ||
      params.get("category_ids") ||
      params.get("expenses_only") ||
      params.get("income_only") ||
      params.get("life_domain") ||
      params.get("filter") ||
      params.get("unconverted") ||
      params.get("q") ||
      params.get("hide_transfers") === "1" ||
      params.get("hide_transfers") === "0" ||
      params.get("focus") ||
      params.get("vendor") ||
      params.get("focus_key") ||
      params.get("rule") ||
      params.get("tx"),
  );
}

export function screenFromSearchParams(params: URLSearchParams): CategorizeScreen {
  // Drill always shows the transaction list (one primary surface).
  if (
    params.get("focus") ||
    params.get("vendor") ||
    params.get("focus_key") ||
    params.get("rule")
  ) {
    return "txs";
  }
  const mode = params.get("mode");
  if (mode && WINDOW_MODES.has(mode)) return mode as CategorizeScreen;
  const panel = params.get("panel");
  if (panel === "grokplus") return "grokplus";
  if (panel === "rules") return "rules";
  if (hasListScope(params)) return "txs";
  return "hub";
}

export function hubParamPatch(): Record<string, string | null> {
  return { mode: null, panel: null };
}

/** Explicit window identity. Omit-mode is hub — leftovers must write mode=review. */
export function windowParamPatch(win: WindowId): Record<string, string | null> {
  if (win === "grokplus") {
    return { mode: null, panel: "grokplus" };
  }
  return { mode: win, panel: null };
}

export function workspaceModeParamPatch(
  next: WorkspaceMode,
): Record<string, string | null> {
  return windowParamPatch(next);
}

export function applyParamPatch(
  params: URLSearchParams,
  patch: Record<string, string | null>,
): URLSearchParams {
  const out = new URLSearchParams(params);
  for (const [key, value] of Object.entries(patch)) {
    if (value == null || value === "") out.delete(key);
    else out.set(key, value);
  }
  return out;
}

export function applyWorkspaceMode(
  params: URLSearchParams,
  next: WorkspaceMode,
): URLSearchParams {
  return applyParamPatch(params, workspaceModeParamPatch(next));
}

/** Absolute Categorize href from a param patch (hub Links push this path). */
export function categorizeHref(patch: Record<string, string | null>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(patch)) {
    if (value != null && value !== "") params.set(key, value);
  }
  const qs = params.toString();
  return qs ? `${CATEGORIZE_PATH}?${qs}` : CATEGORIZE_PATH;
}

export type DrillSrc = "review" | "grokplus" | "rules" | "categories" | "hub" | "hub_usd";

/** Filter keys each src click is allowed to revert on undrill (plus mode/panel/src). */
export const DRILL_WRITES: Record<DrillSrc, readonly string[]> = {
  hub: ["category_id"],
  hub_usd: ["category_id", "expenses_only"],
  review: ["focus", "vendor", "focus_key"],
  grokplus: ["focus", "focus_key"],
  rules: ["rule", "hide_transfers"],
  categories: ["category_id", "category_ids"],
};

export const FOCUS_MAX_CHARS = 1800;

export function parseFocusIds(value: string | null | undefined): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export type DrillParamInput = {
  src: DrillSrc;
  focus?: string[] | null;
  vendor?: string | null;
  focus_key?: string | null;
  rule?: string | null;
  category_id?: string | null;
  category_ids?: string | null;
  hide_transfers?: string | null;
  expenses_only?: string | null;
};

export function drillParamPatch(input: DrillParamInput): Record<string, string | null> {
  const out: Record<string, string | null> = {
    mode: "txs",
    src: input.src,
    panel: null,
    focus: null,
    vendor: null,
    focus_key: null,
    rule: null,
  };
  if (input.focus && input.focus.length > 0) {
    out.focus = input.focus.join(",");
  }
  if (input.vendor) out.vendor = input.vendor;
  if (input.focus_key) out.focus_key = input.focus_key;
  if (input.rule) out.rule = input.rule;
  if (input.category_id !== undefined) out.category_id = input.category_id;
  if (input.category_ids !== undefined) out.category_ids = input.category_ids;
  if (input.hide_transfers !== undefined) out.hide_transfers = input.hide_transfers;
  if (input.expenses_only !== undefined) out.expenses_only = input.expenses_only;
  return out;
}

export function undrillParamPatch(
  params: URLSearchParams,
): Record<string, string | null> {
  const src = params.get("src");
  const out: Record<string, string | null> = {
    focus: null,
    vendor: null,
    focus_key: null,
    rule: null,
    tx: null,
    src: null,
    mode: null,
    panel: null,
  };
  switch (src) {
    case "review":
      out.mode = "review";
      break;
    case "grokplus":
      out.panel = "grokplus";
      break;
    case "rules":
      out.mode = "rules";
      out.hide_transfers = null;
      break;
    case "categories":
      out.mode = "categories";
      out.category_id = null;
      out.category_ids = null;
      break;
    case "hub_usd":
      out.category_id = null;
      out.expenses_only = null;
      break;
    case "hub":
      out.category_id = null;
      break;
    default:
      break;
  }
  return out;
}

export type AllowlistWrite =
  | { type: "focus"; ids: string[] }
  | { type: "vendor"; vendor: string }
  | { type: "focus_key" };

/** Prefer focus=; leftover-only vendor= overflow; never vendor= for Grok+. */
export function chooseAllowlistWrite(input: {
  ids: string[];
  src: "review" | "grokplus";
  leftoverVendorKey?: string | null;
  fetchedMissing: boolean;
}): AllowlistWrite {
  if (input.ids.join(",").length <= FOCUS_MAX_CHARS) {
    return { type: "focus", ids: input.ids };
  }
  if (
    input.src === "review" &&
    input.leftoverVendorKey &&
    input.leftoverVendorKey !== "none" &&
    !input.fetchedMissing
  ) {
    return { type: "vendor", vendor: input.leftoverVendorKey };
  }
  return { type: "focus_key" };
}

export function windowTitle(screen: CategorizeScreen): string {
  switch (screen) {
    case "review":
      return "Review leftovers";
    case "grokplus":
      return "Ask Grok+";
    case "rules":
      return "Rules";
    case "categories":
      return "Categories";
    case "txs":
      return "Transactions";
    default:
      return "";
  }
}

export function srcWindowLabel(src: string | null): string | null {
  switch (src) {
    case "review":
      return "Review leftovers";
    case "grokplus":
      return "Ask Grok+";
    case "rules":
      return "Rules";
    case "categories":
      return "Categories";
    default:
      return null;
  }
}

export type SimRestorePhase = "idle" | "next_steps" | "reviewing_similar";

/** Browser Back pops the similar push; it does not run undrillParamPatch. */
export function shouldRestoreNextStepsFromSimilar(
  phase: SimRestorePhase,
  screen: CategorizeScreen,
  params: URLSearchParams,
): boolean {
  if (phase !== "reviewing_similar") return false;
  if (screen !== "review") return false;
  return !params.get("focus") && !params.get("vendor") && !params.get("focus_key");
}
