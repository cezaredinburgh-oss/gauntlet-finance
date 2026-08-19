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

/** Tablist helper. Screen identity is screenFromSearchParams (omit-mode is hub). */
export function modeFromSearchParams(params: URLSearchParams): WorkspaceMode {
  const screen = screenFromSearchParams(params);
  if (screen === "rules" || screen === "categories") return screen;
  return "review";
}

export function isGrokPlusOverlay(params: URLSearchParams): boolean {
  return params.get("panel") === "grokplus";
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

/** Tablist writes. Review is no longer the omit-mode default. */
export function workspaceModeParamPatch(
  next: WorkspaceMode,
): Record<string, string | null> {
  return windowParamPatch(next);
}

export function applyWorkspaceMode(
  params: URLSearchParams,
  next: WorkspaceMode,
): URLSearchParams {
  const out = new URLSearchParams(params);
  const patch = workspaceModeParamPatch(next);
  for (const [key, value] of Object.entries(patch)) {
    if (value == null || value === "") out.delete(key);
    else out.set(key, value);
  }
  return out;
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
