export const MODES = [
  { id: "review", label: "Review" },
  { id: "rules", label: "Rules" },
  { id: "categories", label: "Categories" },
] as const;

export type WorkspaceMode = (typeof MODES)[number]["id"];

/** Query contract: mode= wins; else panel=rules → rules; else review. panel=grokplus is Review overlay. */
export function modeFromSearchParams(params: URLSearchParams): WorkspaceMode {
  const m = params.get("mode");
  if (m === "rules" || m === "categories" || m === "review") return m;
  if (params.get("panel") === "rules") return "rules";
  return "review";
}

export function isGrokPlusOverlay(params: URLSearchParams): boolean {
  return params.get("panel") === "grokplus";
}

/** Writes mode (omit when review) and always clears panel. */
export function workspaceModeParamPatch(
  next: WorkspaceMode,
): Record<string, string | null> {
  return { mode: next === "review" ? null : next, panel: null };
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
